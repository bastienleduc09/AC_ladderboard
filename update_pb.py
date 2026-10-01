from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

try:
    import pylnk3

    HAS_PYLNK = True
except ImportError:
    HAS_PYLNK = False

# Optional: Set your Assetto Corsa root path here to read friendly names from ui_car.json / ui_track.json
AC_ROOT_PATH = None  # Example: Path(r"C:\Program Files (x86)\Steam\steamapps\common\assettocorsa")


def resolve_ini_path(filepath):
    """Resolves a file path, handling Windows .lnk shortcuts if necessary."""
    if filepath.suffix.lower() == ".lnk":
        if not HAS_PYLNK:
            raise ImportError(
                f"Found shortcut {filepath.name}, but 'pylnk3' is not installed. "
                "Install it via 'pip install pylnk3' to parse .lnk shortcuts."
            )
        shortcut = pylnk3.parse(str(filepath))
        target_path = Path(shortcut.path)
        if not target_path.exists():
            raise FileNotFoundError(
                f"Shortcut {filepath.name} points to non-existent path:"
                f" {target_path}"
            )
        return target_path
    return filepath


def get_car_display_name(car_folder):
    """Reads the friendly car name from ui/ui_car.json if AC_ROOT_PATH is set."""
    if AC_ROOT_PATH:
        ui_json = AC_ROOT_PATH / "content" / "cars" / car_folder / "ui" / "ui_car.json"
        if ui_json.exists():
            try:
                data = json.loads(ui_json.read_text(encoding="utf-8", errors="ignore"))
                brand = data.get("brand", "")
                name = data.get("name", "")
                if brand and name:
                    return f"{brand} {name}"
                elif name:
                    return name
            except Exception:
                pass
    return car_folder.replace("_", " ").title()


def get_track_display_name(track_and_layout):
    """Reads the friendly track and layout name from ui files if AC_ROOT_PATH is set."""
    if AC_ROOT_PATH:
        parts = track_and_layout.split("-", 1)
        track_name = parts[0]
        layout_name = parts[1] if len(parts) > 1 else None

        track_dir = AC_ROOT_PATH / "content" / "tracks" / track_name
        if layout_name:
            ui_json = track_dir / "ui" / layout_name / "ui_track.json"
            if not ui_json.exists():
                ui_json = track_dir / "ui" / f"{layout_name}.json"
        else:
            ui_json = track_dir / "ui" / "ui_track.json"

        if ui_json.exists():
            try:
                data = json.loads(ui_json.read_text(encoding="utf-8", errors="ignore"))
                t_name = data.get("name", track_name)
                l_name = data.get("layout", layout_name)
                if l_name:
                    return f"{t_name} - {l_name}"
                return t_name
            except Exception:
                pass

    return track_and_layout.replace("_", " ").title()


def parse_ini(filepath):
    """Parses an Assetto Corsa personalbest.ini file.

    - GT3 and ETRC classes are grouped by track (only the fastest car per track in those classes is kept).
    - Non-grouped cars are kept individually by (car, track).
    """
    records = {}
    resolved_path = resolve_ini_path(filepath)
    if not resolved_path.exists():
        return records

    with open(resolved_path, "r", encoding="utf-8", errors="ignore") as f:
        current_car = None
        current_track = None
        current_time = float("inf")
        current_date = 0

        for line in f:
            line = line.strip()
            if not line or line.startswith(";"):
                continue

            match = re.match(r"^\[(.+?)@(.+)\]$", line)
            if match:
                if current_track and current_car:
                    car_lower = current_car.lower()
                    if "gt3" in car_lower:
                        key = ("GT3_CLASS", current_track)
                    elif "etrc" in car_lower:
                        key = ("ETRC_CLASS", current_track)
                    else:
                        key = (current_car, current_track)

                    if key not in records or current_time < records[key]["time"]:
                        records[key] = {
                            "car": current_car,
                            "time": current_time,
                            "date": current_date,
                        }

                car_candidate, track_candidate = match.groups()
                current_car = car_candidate
                current_track = track_candidate
                current_time = float("inf")
                current_date = 0

            elif current_track and current_car and "=" in line:
                key, val = line.split("=", 1)
                key = key.strip().upper()
                val = val.strip()
                if key == "TIME":
                    try:
                        current_time = int(val)
                    except ValueError:
                        pass
                elif key == "DATE":
                    try:
                        current_date = int(val)
                    except ValueError:
                        pass

        if current_track and current_car:
            car_lower = current_car.lower()
            if "gt3" in car_lower:
                key = ("GT3_CLASS", current_track)
            elif "etrc" in car_lower:
                key = ("ETRC_CLASS", current_track)
            else:
                key = (current_car, current_track)

            if key not in records or current_time < records[key]["time"]:
                records[key] = {
                    "car": current_car,
                    "time": current_time,
                    "date": current_date,
                }

    return records


def format_time(ms_int):
    """Converts milliseconds integer into mm:ss.ms string."""
    if ms_int == float("inf") or ms_int is None:
        return "N/A"
    total_seconds = ms_int / 1000.0
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:06.3f}"


def format_date(timestamp_ms):
    """Converts a Unix epoch timestamp in milliseconds to YYYY-MM-DD."""
    if not timestamp_ms:
        return "N/A"
    try:
        dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return "N/A"


def generate_pilot_rows(user_data, opponent_data):
    """Generates rows for records/combos that the pilot has that the opponent doesn't."""
    rows = []
    for key, u_info in sorted(user_data.items(), key=lambda x: str(x[0])):
        if u_info["time"] == float("inf"):
            continue
        
        if key not in opponent_data:
            class_type = key[0]
            track = key[1]
            
            track_display = get_track_display_name(track)
            car_display = get_car_display_name(u_info["car"])
            best_time = format_time(u_info["time"])
            best_date = format_date(u_info["date"])
            sort_date_val = u_info["date"] or 0

            if class_type == "GT3_CLASS":
                sort_track_val = f"GT3 - {track}"
            elif class_type == "ETRC_CLASS":
                sort_track_val = f"ETRC - {track}"
            else:
                sort_track_val = f"{u_info['car']} - {track}"

            rows.append(
                f"<tr>"
                f'<td data-sort="{sort_track_val}">{track_display}</td>'
                f'<td data-sort="{u_info["car"]}">{car_display}</td>'
                f'<td data-sort="{u_info["time"]}">{best_time}</td>'
                f'<td data-sort="{sort_date_val}">{best_date}</td>'
                f"</tr>"
            )
            
    if not rows:
        return '<tr><td colspan="4" style="text-align: center;">No exclusive records found.</td></tr>'
    return "".join(rows)


def main():
    pb_dir = Path("./pb")
    output_file = Path("index.html")

    ini_files = list(pb_dir.glob("*.ini")) + list(pb_dir.glob("*.lnk"))

    if len(ini_files) < 2:
        print(
            "Error: Expected at least two personalbest files (ini or lnk) in the"
            " './pb/' directory to compare."
        )
        return

    user1_path, user2_path = ini_files[0], ini_files[1]
    user1_name = user1_path.stem
    user2_name = user2_path.stem

    try:
        user1_data = parse_ini(user1_path)
        user2_data = parse_ini(user2_path)
    except Exception as e:
        print(f"Error reading user files: {e}")
        if not HAS_PYLNK:
            print("Tip: If your files are .lnk shortcuts, run: pip install pylnk3")
        return

    all_keys = set(user1_data.keys()).intersection(set(user2_data.keys()))

    table_rows = []
    if not all_keys:
        table_rows.append(
            '<tr><td colspan="8" style="text-align: center;">No track records'
            " found between the two users.</td></tr>"
        )
    else:
        for key in sorted(all_keys, key=lambda x: str(x)):
            u1_info = user1_data.get(key, {"car": "", "time": float("inf"), "date": 0})
            u2_info = user2_data.get(key, {"car": "", "time": float("inf"), "date": 0})

            # Determine best and next best between user1 and user2 for this key
            if u1_info["time"] <= u2_info["time"]:
                best_car = u1_info["car"]
                best_time_val = u1_info["time"]
                best_date_val = u1_info["date"] or 0
                best_holder = f"<strong>{user1_name}</strong>"

                next_car = u2_info["car"]
                next_time_val = u2_info["time"]
                next_date_val = u2_info["date"] or 0
                next_holder = f"<strong>{user2_name}</strong>" if next_time_val != float("inf") else "N/A"
            else:
                best_car = u2_info["car"]
                best_time_val = u2_info["time"]
                best_date_val = u2_info["date"] or 0
                best_holder = f"<strong>{user2_name}</strong>"

                next_car = u1_info["car"]
                next_time_val = u1_info["time"]
                next_date_val = u1_info["date"] or 0
                next_holder = f"<strong>{user1_name}</strong>" if next_time_val != float("inf") else "N/A"

            class_type = key[0]
            track = key[1]

            track_display = get_track_display_name(track)
            
            # Best fields
            best_car_display = get_car_display_name(best_car) if best_car else "N/A"
            best_time_str = format_time(best_time_val)
            best_date_str = format_date(best_time_val != float("inf") and best_date_val or 0)

            # Next best fields
            next_car_display = get_car_display_name(next_car) if next_car and next_time_val != float("inf") else "N/A"
            next_time_str = format_time(next_time_val)
            next_date_str = format_date(next_time_val != float("inf") and next_date_val or 0)

            if class_type == "GT3_CLASS":
                sort_track_val = f"GT3 - {track}"
            elif class_type == "ETRC_CLASS":
                sort_track_val = f"ETRC - {track}"
            else:
                sort_track_val = f"{best_car} - {track}"

            table_rows.append(
                f"<tr>"
                f'<td data-sort="{sort_track_val}">{track_display}</td>'
                f'<td data-sort="{best_car}">{best_car_display}</td>'
                f'<td data-sort="{best_time_val}">{best_time_str}</td>'
                f'<td data-sort="{best_date_val}">{best_date_str}</td>'
                f'<td>{best_holder}</td>'
                f'<td data-sort="{next_time_val}">{next_time_str}</td>'
                f'<td data-sort="{next_date_val}">{next_date_str}</td>'
                f'<td>{next_holder}</td>'
                f"</tr>"
            )

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Assetto Corsa Shared Leaderboard</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 40px;
            background-color: #0d1117;
            color: #c9d1d9;
        }}
        h1 {{
            font-size: 1.5rem;
            border-bottom: 1px solid #30363d;
            padding-bottom: 0.3rem;
        }}
        p.subtitle {{
            color: #8b949e;
            margin-bottom: 20px;
        }}
        .nav-links {{
            margin-bottom: 20px;
        }}
        .nav-links a {{
            color: #58a6ff;
            text-decoration: none;
            margin-right: 15px;
            font-weight: 500;
        }}
        .nav-links a:hover {{
            text-decoration: underline;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
            background-color: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            overflow: hidden;
        }}
        th, td {{
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid #30363d;
        }}
        th {{
            background-color: #21262d;
            color: #f0f6fc;
            cursor: pointer;
            user-select: none;
            position: relative;
        }}
        th:hover {{
            background-color: #30363d;
        }}
        th::after {{
            content: " ↕";
            font-size: 0.8rem;
            color: #8b949e;
        }}
        tr:last-child td {{
            border-bottom: none;
        }}
        tr:hover td {{
            background-color: #1f242c;
        }}
    </style>
</head>
<body>
    <h1>Assetto Corsa Shared Leaderboard</h1>
    <p class="subtitle">Comparing: <strong>{user1_name}</strong> vs <strong>{user2_name}</strong> (GT3 & ETRC classes combined per track, other cars per track/car combination)</p>
    
    <div class="nav-links">
        <a href="{user1_name.lower()}.html">View Exclusive Records for {user1_name}</a>
        <a href="{user2_name.lower()}.html">View Exclusive Records for {user2_name}</a>
    </div>

    <table id="leaderboard">
        <thead>
            <tr>
                <th onclick="sortTable(0)">Track</th>
                <th onclick="sortTable(1)">Best Car</th>
                <th onclick="sortTable(2, true)">Best Lap Time</th>
                <th onclick="sortTable(3, true)">Date</th>
                <th onclick="sortTable(4)">Holder</th>
                <th onclick="sortTable(5, true)">Next Best Time</th>
                <th onclick="sortTable(6, true)">Next Date</th>
                <th onclick="sortTable(7)">Next Holder</th>
            </tr>
        </thead>
        <tbody>
            {"".join(table_rows)}
        </tbody>
    </table>

    <script>
    function sortTable(colIndex, isNumeric = false) {{
        const table = document.getElementById("leaderboard");
        const tbody = table.tBodies[0];
        const rows = Array.from(tbody.querySelectorAll("tr"));
        
        const currentDir = table.getAttribute("data-sort-dir") === "asc" ? "desc" : "asc";
        table.setAttribute("data-sort-dir", currentDir);

        rows.sort((a, b) => {{
            let cellA = a.cells[colIndex];
            let cellB = b.cells[colIndex];

            let valA = cellA.getAttribute("data-sort") !== null ? cellA.getAttribute("data-sort") : cellA.textContent.trim();
            let valB = cellB.getAttribute("data-sort") !== null ? cellB.getAttribute("data-sort") : cellB.textContent.trim();

            if (isNumeric) {{
                valA = parseFloat(valA) || 0;
                valB = parseFloat(valB) || 0;
            }} else {{
                valA = valA.toLowerCase();
                valB = valB.toLowerCase();
            }}

            if (valA < valB) return currentDir === "asc" ? -1 : 1;
            if (valA > valB) return currentDir === "asc" ? 1 : -1;
            return 0;
        }});

        rows.forEach(row => tbody.appendChild(row));
    }}
    </script>
</body>
</html>
"""

    output_file.write_text(html_content, encoding="utf-8")
    print(f"Interactive HTML leaderboard generated at {output_file.resolve()}")

    # Generate child pages for each pilot
    for pilot_name, pilot_data, opponent_data in [
        (user1_name, user1_data, user2_data),
        (user2_name, user2_data, user1_data)
    ]:
        pilot_page_path = Path(f"{pilot_name.lower()}.html")
        pilot_rows_html = generate_pilot_rows(pilot_data, opponent_data)
        
        pilot_html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Exclusive Records - {pilot_name}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 40px;
            background-color: #0d1117;
            color: #c9d1d9;
        }}
        h1 {{
            font-size: 1.5rem;
            border-bottom: 1px solid #30363d;
            padding-bottom: 0.3rem;
        }}
        p.subtitle {{
            color: #8b949e;
            margin-bottom: 20px;
        }}
        .nav-links {{
            margin-bottom: 20px;
        }}
        .nav-links a {{
            color: #58a6ff;
            text-decoration: none;
            font-weight: 500;
        }}
        .nav-links a:hover {{
            text-decoration: underline;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
            background-color: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            overflow: hidden;
        }}
        th, td {{
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid #30363d;
        }}
        th {{
            background-color: #21262d;
            color: #f0f6fc;
            cursor: pointer;
            user-select: none;
            position: relative;
        }}
        th:hover {{
            background-color: #30363d;
        }}
        th::after {{
            content: " ↕";
            font-size: 0.8rem;
            color: #8b949e;
        }}
        tr:last-child td {{
            border-bottom: none;
        }}
        tr:hover td {{
            background-color: #1f242c;
        }}
    </style>
</head>
<body>
    <div class="nav-links">
        <a href="index.html">&larr; Back to Main Leaderboard</a>
    </div>
    
    <h1>Exclusive Records for {pilot_name}</h1>
    <p class="subtitle">GT3 & ETRC tracks and other car/track combos where <strong>{pilot_name}</strong> has a record that the other pilot doesn't hold or hasn't raced.</p>
    
    <table id="pilot-leaderboard">
        <thead>
            <tr>
                <th onclick="sortTable(0)">Track</th>
                <th onclick="sortTable(1)">Car</th>
                <th onclick="sortTable(2, true)">Lap Time</th>
                <th onclick="sortTable(3, true)">Date</th>
            </tr>
        </thead>
        <tbody>
            {pilot_rows_html}
        </tbody>
    </table>

    <script>
    function sortTable(colIndex, isNumeric = false) {{
        const table = document.getElementById("pilot-leaderboard");
        const tbody = table.tBodies[0];
        const rows = Array.from(tbody.querySelectorAll("tr"));
        
        const currentDir = table.getAttribute("data-sort-dir") === "asc" ? "desc" : "asc";
        table.setAttribute("data-sort-dir", currentDir);

        rows.sort((a, b) => {{
            let cellA = a.cells[colIndex];
            let cellB = b.cells[colIndex];

            if (!cellA || !cellB) return 0;

            let valA = cellA.getAttribute("data-sort") !== null ? cellA.getAttribute("data-sort") : cellA.textContent.trim();
            let valB = cellB.getAttribute("data-sort") !== null ? cellB.getAttribute("data-sort") : cellB.textContent.trim();

            if (isNumeric) {{
                valA = parseFloat(valA) || 0;
                valB = parseFloat(valB) || 0;
            }} else {{
                valA = valA.toLowerCase();
                valB = valB.toLowerCase();
            }}

            if (valA < valB) return currentDir === "asc" ? -1 : 1;
            if (valA > valB) return currentDir === "asc" ? 1 : -1;
            return 0;
        }});

        rows.forEach(row => tbody.appendChild(row));
    }}
    </script>
</body>
</html>
"""
        pilot_page_path.write_text(pilot_html_content, encoding="utf-8")
        print(f"Child page generated for {pilot_name} at {pilot_page_path.resolve()}")

    try:
        subprocess.run(
            ["git", "add", str(output_file), f"{user1_name.lower()}.html", f"{user2_name.lower()}.html"], check=True, capture_output=True
        )
        status = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], capture_output=True
        )
        if status.returncode != 0:
            subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    "Auto-update leaderboard adding next best lap time, date, and holder columns via update_pb.py",
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(["git", "push"], check=True, capture_output=True)
            print("Successfully committed and pushed leaderboard updates to GitHub.")
        else:
            print("No changes detected to commit.")
    except Exception as e:
        print(f"Git auto-commit/push skipped or failed: {e}")


if __name__ == "__main__":
    main()