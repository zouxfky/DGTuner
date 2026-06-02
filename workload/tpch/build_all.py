from pathlib import Path


TPCH_DIR = Path(__file__).resolve().parent
QUERY_DIR = TPCH_DIR / "queries"
OUTPUT_PATH = TPCH_DIR / "all.sql"


def main():
    query_paths = sorted(QUERY_DIR.glob("q*.sql"))
    if len(query_paths) != 22:
        raise ValueError(f"Expected 22 TPC-H query files, found {len(query_paths)} in {QUERY_DIR}")

    with OUTPUT_PATH.open("w", encoding="utf-8") as output:
        for path in query_paths:
            output.write(f"-- {path.name}\n")
            output.write(path.read_text(encoding="utf-8").strip().rstrip(";") + ";\n\n")

    print(f"Wrote {OUTPUT_PATH} from {len(query_paths)} query files.")


if __name__ == "__main__":
    main()
