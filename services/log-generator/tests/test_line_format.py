import re

LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z (INFO|WARN|ERROR) [a-z]+ .+$"
)


def test_line_format_matches_contract(generator, tmp_path, read_lines):
    lines = []
    for _ in range(200):
        level = generator.rng.choice(("INFO", "WARN", "ERROR"))
        lines.append(generator.make_line(level))
        generator.write_line(generator.make_line(level))
    for line in lines:
        assert LINE_RE.match(line), f"bad line: {line!r}"
    for line in read_lines(tmp_path / "app.log"):
        assert LINE_RE.match(line), f"bad written line: {line!r}"