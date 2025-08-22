import logging
import re
from collections import Counter, defaultdict


class SubMerger:
    # Keep your existing __init__ that defines self.settings_dir

    # ----------------------------- Parsing & Time -----------------------------
    @staticmethod
    def _ass_time_to_ms(t: str) -> int:
        h, m, s_cs = t.split(":")
        s, cs = s_cs.split(".")
        return (int(h) * 3600 + int(m) * 60 + int(s)) * 1000 + int(cs) * 10

    @staticmethod
    def _ms_to_ass_time(ms: int) -> str:
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        cs = ms // 10
        return f"{h:01}:{m:02}:{s:02}.{cs:02}"

    @staticmethod
    def _overlaps(a_start, a_end, b_start, b_end) -> bool:
        return max(a_start, b_start) < min(a_end, b_end)

    @staticmethod
    def _parse_ass_file(sub_lines):
        styles, events = {}, []
        current_section = None
        for raw in sub_lines:
            line = raw.rstrip("\n")
            low = line.strip().lower()
            if low == "[v4+ styles]":
                current_section = "styles"
            elif low == "[events]":
                current_section = "events"
            elif line.strip().startswith("["):
                current_section = None

            if current_section == "styles" and line.lower().startswith("style:"):
                try:
                    name = line.split(":", 1)[1].split(",")[0].strip()
                    styles[name] = line
                except Exception:
                    logging.warning(f"Could not parse style: {line}")
            elif current_section == "events" and (
                line.lower().startswith("dialogue:")
                or line.lower().startswith("comment:")
            ):
                events.append(line)
        return styles, events

    # ----------------------------- Styles -----------------------------
    @staticmethod
    def _build_master_styles():
        return {
            "Top-Primary": "Style: Top-Primary,Roboto,56,&H00FFFFFF,&H000000FF,&H00000000,&H99000000,-1,0,0,0,100,100,0,0,1,2.5,2,8,20,20,25,1",
            "Top-Secondary": "Style: Top-Secondary,Roboto,48,&H00FFFFFF,&H000000FF,&H00000000,&H99000000,-1,-1,0,0,100,100,0,0,1,2.5,2,8,20,20,25,1",
            "Bottom-Primary-Normal": "Style: Bottom-Primary-Normal,OGOA6OWA,62,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2.5,0,2,20,20,35,1",
            "Bottom-Primary-Raised": "Style: Bottom-Primary-Raised,OGOA6OWA,62,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2.5,0,2,20,20,90,1",
            "Bottom-Secondary": "Style: Bottom-Secondary,OGOA6OWA,54,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,-1,0,0,100,100,0,0,1,2.5,0,2,20,20,30,1",
        }

    @staticmethod
    def _create_top_style_map(original_styles, events):
        style_map = {}
        known_primary = {"Default"}
        known_secondary = {"Italics", "On Top Italic", "On Top", "OS"}
        for style_name in original_styles.keys():
            if style_name in known_primary:
                style_map[style_name] = "Top-Primary"
            elif style_name in known_secondary:
                style_map[style_name] = "Top-Secondary"
        if not style_map:
            dialogue_events = [l for l in events if l.lower().startswith("dialogue:")]
            if dialogue_events:
                style_counts = Counter(
                    l.split(",", 9)[3].strip() for l in dialogue_events
                )
                if style_counts:
                    primary = style_counts.most_common(1)[0][0]
                    style_map[primary] = "Top-Primary"
                    if len(style_counts) > 1:
                        sec = [
                            s for s, _ in style_counts.most_common(2) if s != primary
                        ]
                        if sec:
                            style_map[sec[0]] = "Top-Secondary"
        return style_map

    # ----------------------------- Event utilities -----------------------------
    @staticmethod
    def _event_parts(line):
        low = line.lower()
        is_ev = low.startswith("dialogue:") or low.startswith("comment:")
        if not is_ev:
            return False, None
        parts = line.split(",", 9)
        return True, parts

    @staticmethod
    def _strip_positioning_tags(text: str) -> str:
        return re.sub(
            r"\{\\[^}]*?(?:an\d|pos|move|org)[^}]*\}", "", text, flags=re.IGNORECASE
        )

    @staticmethod
    def _has_explicit_positioning(s: str) -> bool:
        return bool(
            re.search(r"\{\\(?:pos|move|org|an\d)\b.*?\}", s, flags=re.IGNORECASE)
        )

    @staticmethod
    def _is_top_aligned(text: str) -> bool:
        pos = re.search(r"\\pos\(([^)]+)\)", text)
        if pos:
            parts = [p.strip() for p in pos.group(1).split(",")]
            if len(parts) >= 2:
                try:
                    return float(parts[1]) < 540
                except ValueError:
                    pass
        move = re.search(r"\\move\(([^)]+)\)", text)
        if move:
            parts = [p.strip() for p in move.group(1).split(",")]
            if len(parts) >= 4:
                try:
                    y1, y2 = float(parts[1]), float(parts[3])
                    return y1 < 540 and y2 < 540
                except ValueError:
                    pass
        an = re.search(r"\\an(\d)", text)
        if an:
            n = int(an.group(1))
            return n >= 7 or (4 <= n <= 6)
        return False

    @staticmethod
    def _force_vertical_region(text: str, to_top: bool) -> str:
        def fix_an(match):
            n = int(match.group(1))
            if to_top:
                if n <= 3:
                    n += 6
                elif n <= 6:
                    n += 3
            else:
                if n >= 7:
                    n -= 6
                elif n >= 4:
                    n -= 3
            return f"\\an{n}"

        def fix_pos(match):
            parts = [p.strip() for p in match.group(1).split(",")]
            x, y = map(float, parts[:2])
            if to_top and y > 540:
                y -= 540
            elif not to_top and y < 540:
                y += 540
            return f"\\pos({x:g},{y:g})"

        def fix_move(match):
            parts = [p.strip() for p in match.group(1).split(",")]
            x1, y1, x2, y2 = map(float, parts[:4])
            if to_top:
                if y1 > 540:
                    y1 -= 540
                if y2 > 540:
                    y2 -= 540
            else:
                if y1 < 540:
                    y1 += 540
                if y2 < 540:
                    y2 += 540
            rest = parts[4:]
            coords = [f"{x1:g}", f"{y1:g}", f"{x2:g}", f"{y2:g}", *rest]
            return "\\move(" + ",".join(coords) + ")"

        text = re.sub(r"\\an(\d)", fix_an, text)
        text = re.sub(r"\\pos\(([^)]+)\)", fix_pos, text)
        text = re.sub(r"\\move\(([^)]+)\)", fix_move, text)
        return text

    @staticmethod
    def _ensure_top_position(text: str) -> str:
        return SubMerger._force_vertical_region(text, True)

    @staticmethod
    def _ensure_bottom_position(text: str) -> str:
        return SubMerger._force_vertical_region(text, False)

    @staticmethod
    def _collect_change_points(events, style_filter):
        points = set()
        for line in events:
            ok, p = SubMerger._event_parts(line)
            if not ok:
                continue
            style = p[3].strip()
            if style_filter(style):
                points.add(SubMerger._ass_time_to_ms(p[1].strip()))
                points.add(SubMerger._ass_time_to_ms(p[2].strip()))
        return points

    @staticmethod
    def _split_events_on_points(events, points, style_predicate):
        if not points:
            return events[:]
        out = []
        for line in events:
            ok, parts = SubMerger._event_parts(line)
            if not ok:
                out.append(line)
                continue
            style = parts[3].strip()
            if not style_predicate(style):
                out.append(line)
                continue
            s = SubMerger._ass_time_to_ms(parts[1].strip())
            e = SubMerger._ass_time_to_ms(parts[2].strip())
            cuts = sorted({s, e, *(p for p in points if s < p < e)})
            if len(cuts) == 2:
                out.append(line)
                continue
            for i in range(len(cuts) - 1):
                newp = parts[:]
                newp[1] = SubMerger._ms_to_ass_time(cuts[i])
                newp[2] = SubMerger._ms_to_ass_time(cuts[i + 1])
                out.append(",".join(newp))
        return out

    # ----------------------------- Top (English) pipeline -----------------------------
    @staticmethod
    def _normalize_top(events, style_map):
        is_primary = lambda st: style_map.get(st) == "Top-Primary"
        is_secondary = lambda st: style_map.get(st) == "Top-Secondary"

        primary_points = SubMerger._collect_change_points(events, is_primary)
        ev1 = SubMerger._split_events_on_points(events, primary_points, is_secondary)
        secondary_points = SubMerger._collect_change_points(ev1, is_secondary)
        ev2 = SubMerger._split_events_on_points(ev1, secondary_points, is_primary)

        org_stripper = re.compile(r"\{\\[^\}]*?org[^\}]*\}", re.IGNORECASE)
        buckets = defaultdict(list)
        order = []
        for line in ev2:
            ok, p = SubMerger._event_parts(line)
            if not ok:
                buckets[("RAW", len(order))].append(line)
                order.append(("RAW", len(order)))
                continue
            s = SubMerger._ass_time_to_ms(p[1].strip())
            e = SubMerger._ass_time_to_ms(p[2].strip())
            key = (s, e)
            if key not in buckets:
                order.append(key)
            buckets[key].append(p)

        normalized = []
        for key in order:
            if key[0] == "RAW":
                normalized.extend(buckets[key])
                continue
            s, e = key
            primaries, secondaries, others = [], [], []
            for p in buckets[key]:
                st = p[3].strip()
                if SubMerger._has_explicit_positioning(p[9]):
                    others.append(p)
                    continue
                mapped = style_map.get(st)
                if mapped == "Top-Primary":
                    primaries.append(p)
                elif mapped == "Top-Secondary":
                    secondaries.append(p)
                else:
                    others.append(p)

            keep = []
            if primaries:
                keep.append(primaries[0])
                for p in primaries[1:]:
                    p[0] = "Comment:" + p[0].split(":", 1)[1]
                    keep.append(p)
            if secondaries:
                keep.append(secondaries[0])
                for p in secondaries[1:]:
                    p[0] = "Comment:" + p[0].split(":", 1)[1]
                    keep.append(p)

            for p in keep + others:
                st = p[3].strip()
                if SubMerger._has_explicit_positioning(p[9]):
                    if not SubMerger._is_top_aligned(p[9]):
                        p[9] = org_stripper.sub("", SubMerger._ensure_top_position(p[9]))
                    else:
                        p[9] = org_stripper.sub("", p[9])
                    normalized.append(",".join(p))
                else:
                    mapped = style_map.get(st, st)
                    p[3] = mapped
                    p[9] = org_stripper.sub("", SubMerger._ensure_top_position(p[9]))
                    normalized.append(",".join(p))
        return normalized

    # ----------------------------- Bottom (Chinese) pipeline -----------------------------
    @staticmethod
    def _sanitize_and_map_bottom(
        events2, styles2, english_intervals, processable={"sub-cn", "default", "top"}
    ):
        passthrough_styles = {
            "title",
            "screen",
            "opjp",
            "opcn",
            "staff",
            "credit",
            "sign",
            "sfx",
        }

        def is_karaoke_or_template(effect: str, text: str) -> bool:
            return (
                bool(effect.strip())
                or bool(re.search(r"\{\\k\d", text))
                or ("template" in text.lower())
            )

        tag_stripper = re.compile(
            r"\{\\[^\}]*?(?:an|pos|move|org)[^\}]*\}", re.IGNORECASE
        )
        final_events = []
        kept_styles = set()

        def collides_with_top(s_ms, e_ms):
            for ts, te in english_intervals:
                if SubMerger._overlaps(s_ms, e_ms, ts, te):
                    return True
            return False

        for line in events2:
            ok, p = SubMerger._event_parts(line)
            if not ok:
                final_events.append(line)
                continue
            st = p[3].strip()
            effect = p[8]
            text = p[9]

            has_pos = SubMerger._has_explicit_positioning(text)
            s_ms = SubMerger._ass_time_to_ms(p[1].strip())
            e_ms = SubMerger._ass_time_to_ms(p[2].strip())

            if (
                st.casefold() in passthrough_styles
                or is_karaoke_or_template(effect, text)
                or st.casefold() not in processable
            ):
                if has_pos and SubMerger._is_top_aligned(text) and collides_with_top(s_ms, e_ms):
                    p[9] = SubMerger._ensure_bottom_position(text)
                    final_events.append(",".join(p))
                else:
                    final_events.append(line)
                if st in styles2:
                    kept_styles.add(st)
                continue

            if has_pos:
                if SubMerger._is_top_aligned(text) and collides_with_top(s_ms, e_ms):
                    p[9] = SubMerger._ensure_bottom_position(text)
                final_events.append(",".join(p))
                if st in styles2:
                    kept_styles.add(st)
                continue

            text_clean = tag_stripper.sub("", text)
            is_top_like = text.strip().startswith("{\\an8}") or st.casefold() == "top"
            if is_top_like:
                p[3] = "Bottom-Secondary"
            else:
                p[3] = (
                    "Bottom-Primary-Raised"
                    if collides_with_top(s_ms, e_ms)
                    else "Bottom-Primary-Normal"
                )
            p[9] = text_clean
            final_events.append(",".join(p))

        return final_events, kept_styles

    # ----------------------------- Public API -----------------------------
    def merge_subs_for_batch(self, video_file, first_sub, second_sub):
        try:
            sub1_text = first_sub.read_text(
                encoding="utf-8", errors="ignore"
            ).splitlines()
            sub2_text = second_sub.read_text(
                encoding="utf-8", errors="ignore"
            ).splitlines()
            styles1, events1 = self._parse_ass_file(sub1_text)
            styles2, events2 = self._parse_ass_file(sub2_text)

            final_styles = self._build_master_styles()

            style_map1 = self._create_top_style_map(styles1, events1)
            top_events = self._normalize_top(events1, style_map1)

            english_intervals = []
            for line in top_events:
                ok, p = self._event_parts(line)
                if not ok:
                    continue
                if p[0].lower().startswith("dialogue:"):
                    st = p[3].strip()
                    text = p[9]
                    has_pos = self._has_explicit_positioning(text)
                    if (
                        st in ("Top-Primary", "Top-Secondary")
                        or (has_pos and self._is_top_aligned(text))
                    ):
                        s = self._ass_time_to_ms(p[1].strip())
                        e = self._ass_time_to_ms(p[2].strip())
                        english_intervals.append((s, e))

            bottom_events, kept_bottom_styles = self._sanitize_and_map_bottom(
                events2, styles2, english_intervals
            )
            for ks in kept_bottom_styles:
                if ks not in final_styles and ks in styles2:
                    final_styles[ks] = styles2[ks]

            clean_header = [
                "[Script Info]",
                "; Script generated by Dual Subtitle Burner",
                "Title: Merged Subtitle",
                "ScriptType: v4.00+",
                "WrapStyle: 0",
                "PlayResX: 1920",
                "PlayResY: 1080",
                "Collisions: Reverse",
            ]

            merged = []
            merged.extend(clean_header)
            merged.extend(
                [
                    "\n[V4+ Styles]",
                    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
                ]
            )
            merged.extend(sorted(final_styles.values()))
            merged.extend(
                [
                    "\n[Events]",
                    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                ]
            )
            merged.extend(top_events)
            merged.extend(bottom_events)

            out_path = self.settings_dir / f"{video_file.stem}_temp_merged.ass"
            out_path.write_text("\n".join(merged), encoding="utf-8-sig")
            logging.info(f"Successfully merged (normalized) {video_file.name}.")
            return out_path

        except Exception as e:
            logging.error(f"Merge failed for {video_file.name}: {e}", exc_info=True)
            return None
