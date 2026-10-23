"""Small local semantic sanity check without crawling any platform."""

import asyncio

from semif_local import SemIfLocalReviewer


async def main() -> None:
    reviewer = SemIfLocalReviewer()
    try:
        for sentence in (
            "这个公园好可爱。",
            "公园里的小狗好可爱。",
            "在公园拍到了可爱的小猫。",
            "这座公园很可爱，设计得像童话世界。",
        ):
            choice, confidence = await reviewer.decide(("可爱", "公园"), sentence)
            print(f"{sentence} => {choice}, confidence={confidence:.3f}", flush=True)
    finally:
        await reviewer.close()


if __name__ == "__main__":
    asyncio.run(main())
