"""Do xem bien the media that su khac nhau den dau.

    python scripts/demo_media.py

Tao mot video mau, render ban rieng cho 5 tai khoan o ca ba muc do, roi in ra so.
Khong khang dinh "da du khac" - in so de ban tu quyet.

Doc so the nao:
  hash file khac nhau  -> dieu kien can, gan nhu luon dat, pha duoc so khop chinh xac
  pHash lech 0-4       -> voi mot bo so khop tri giac thi van la mot file
  pHash lech 10+       -> bat dau la hai noi dung khac nhau, doi lai la nhin ra duoc
"""

from __future__ import annotations

from itertools import combinations

from seeding.core import media, mediastore

ACCOUNTS = ["acc-1", "acc-2", "acc-3", "acc-4", "acc-5"]
CAMPAIGN = "chien-dich-demo"


def main() -> int:
    if not media.have_ffmpeg():
        print("Khong tim thay ffmpeg.")
        return 1

    source = mediastore.sources_dir() / "demo.mp4"
    if not source.exists():
        print(f"Dang tao video mau tai {source} ...")
        media.make_test_video(source, seconds=3)

    print(f"\nGoc: {source.name}  ({source.stat().st_size / 1024:.0f} KB)")
    print(f"pHash goc: {media.perceptual_hash(source)}\n")

    for strength in media.Strength:
        print(f"{'=' * 66}\n  Muc do: {strength.value}\n{'=' * 66}\n")

        rendered = []
        for acc in ACCOUNTS:
            recipe = media.recipe_for(CAMPAIGN, acc, strength=strength)
            path, phash = mediastore.ensure_variant("demo.mp4", CAMPAIGN, acc, strength=strength)
            rendered.append((acc, path, phash, recipe))

        for acc, path, phash, recipe in rendered:
            size = path.stat().st_size / 1024
            print(f"  {acc:<8} {size:>6.0f} KB  {phash}  {recipe.describe()}")

        files = {media.file_hash(p) for _, p, _, _ in rendered}
        print(f"\n  File khac nhau: {len(files)}/{len(rendered)}")

        base = media.perceptual_hash(source)
        from_source = [media.phash_distance(base, h) for _, _, h, _ in rendered]
        print(f"  pHash lech so voi goc: {min(from_source)}-{max(from_source)}")

        pairs = [media.phash_distance(a[2], b[2]) for a, b in combinations(rendered, 2)]
        print(f"  pHash lech giua cac ban: {min(pairs)}-{max(pairs)}")

        if min(pairs) == 0:
            print("  -> Co hai ban ma bo so khop tri giac van coi la mot file.")
        print()

    print(f"{'=' * 66}")
    print("  Bien doi manh hon thi pHash dich xa hon, nhung nhin ra duoc.")
    print("  Neu nen tang so khop tri giac tot, cau tra loi that nam o cho khac:")
    print("  noi dung goc khac nhau cho tung nhom tai khoan.")
    print(f"{'=' * 66}\n")

    # Goi lai cho cung (campaign, account) phai dung lai file cu, khong render lai -
    # cung tinh than voi idempotency_key ben planner.
    seeds = [(CAMPAIGN, acc) for acc in ACCOUNTS]
    first = mediastore.report("demo.mp4", seeds, strength=media.Strength.MODERATE)
    second = mediastore.report("demo.mp4", seeds, strength=media.Strength.MODERATE)

    print(
        f"Goi lai cho cung (campaign, account): dung lai dung file cu = "
        f"{first['paths'] == second['paths']}"
    )
    # Cac bang o tren co y KHONG bat tranh trung, de nhin thay van de that. Con
    # mediastore.report() thi co bat - so nho nhat phai roi khoi 0.
    print(
        f"\nCung muc moderate nhung CO tranh trung pHash: "
        f"{first['unique_files']}/{first['count']} file khac nhau, "
        f"pHash lech {first['min_phash_distance']}-{first['max_phash_distance']}"
    )
    print("(bang moderate o tren khong bat tranh trung, nen co cap lech 0)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
