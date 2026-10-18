"""Copycat grouping. No network."""
import edge.copycat as copycat


def setup_function():
    copycat.reset_index()


def test_earliest_clean_launch_is_original():
    first = {"symbol": "DOG", "name": "Dog Coin", "pair_created_at": 100, "clean_funding": True, "holders_per_hour": 10}
    second = {"symbol": "DOG", "name": "Dog Coin", "pair_created_at": 200, "clean_funding": True, "holders_per_hour": 90}
    copycat.apply_to_info(first, "mint-old")
    labelled = copycat.apply_to_info(second, "mint-new")
    assert labelled["role"] == "copy"
    assert labelled["original"] == "mint-old"
    assert second["copycat_block_alert"] is True
    again = copycat.resolve(first, "mint-old")
    assert again["role"] == "original"
    assert again["copy_count"] == 1


def test_similar_name_and_image_hash():
    grid = [10] * 32 + [200] * 32
    image_hash = copycat.ahash_bits(grid)
    near = copycat.ahash_bits([12] * 32 + [200] * 32)
    assert copycat.hash_distance(image_hash, near) <= 8
    copycat.apply_to_info(
        {"symbol": "AAA", "name": "Moon Rocket", "image_hash": image_hash, "pair_created_at": 1},
        "a",
    )
    copy = copycat.apply_to_info(
        {"symbol": "AAB", "name": "Moon Rockets", "image_hash": near, "pair_created_at": 2},
        "b",
    )
    assert copy["role"] == "copy"


def test_unrelated_names_stay_separate():
    copycat.apply_to_info({"symbol": "CAT", "name": "Cat", "pair_created_at": 1}, "a")
    other = copycat.apply_to_info({"symbol": "DOG", "name": "Dog", "pair_created_at": 2}, "b")
    assert other["copy_count"] == 0
    assert other["block_alert"] is False
