import random

from seeding.core import hashtags

POOLS = {
    "tech": ["#tech", "#gadgets", "#software", "#devtools", "#coding", "#opensource"],
    "vn": ["#vietnam", "#hanoi", "#saigon"],
}


def test_normalise_adds_the_hash_and_strips_spaces():
    assert hashtags.normalise("  cong nghe ") == "#congnghe"
    assert hashtags.normalise("#already") == "#already"
    assert hashtags.normalise("##double") == "#double"


def test_empty_tag_is_dropped():
    assert hashtags.normalise("   ") == ""
    assert hashtags.clean_pool(["", "  ", "#ok"]) == ["#ok"]


def test_pool_drops_duplicates_case_insensitively():
    assert hashtags.clean_pool(["#Tech", "tech", "#TECH", "#other"]) == ["#Tech", "#other"]


def test_expands_the_requested_number_of_tags():
    out = hashtags.expand("hello [[tags:tech:3]]", POOLS, random.Random(1))
    tags = out.replace("hello ", "").split()
    assert len(tags) == 3
    assert all(t in POOLS["tech"] for t in tags)


def test_never_repeats_a_tag_within_one_placeholder():
    out = hashtags.expand("[[tags:tech:6]]", POOLS, random.Random(2))
    tags = out.split()
    assert len(tags) == len(set(tags))


def test_asking_for_more_than_the_pool_holds_gives_the_whole_pool():
    out = hashtags.expand("[[tags:vn:99]]", POOLS, random.Random(3))
    assert sorted(out.split()) == sorted(POOLS["vn"])


def test_default_count_when_none_given():
    assert len(hashtags.expand("[[tags:tech]]", POOLS, random.Random(4)).split()) == 3


def test_unknown_pool_is_left_visible_instead_of_silently_dropped():
    """Go sai ten tui thi phai nhin thay ngay, khong phai bai len thieu hashtag."""
    out = hashtags.expand("x [[tags:khong-ton-tai:3]]", POOLS, random.Random(5))
    assert "[[tags:khong-ton-tai:3]]" in out


def test_same_seed_gives_the_same_tags():
    """Lap ke hoach lai cho cung mot tai khoan phai ra dung bai cu."""
    a = hashtags.expand("[[tags:tech:3]]", POOLS, random.Random(7))
    b = hashtags.expand("[[tags:tech:3]]", POOLS, random.Random(7))
    assert a == b


def test_different_accounts_get_different_tag_sets():
    outs = {hashtags.expand("[[tags:tech:3]]", POOLS, random.Random(i)) for i in range(30)}
    assert len(outs) > 10


def test_two_placeholders_are_both_expanded():
    out = hashtags.expand("[[tags:tech:2]] and [[tags:vn:2]]", POOLS, random.Random(8))
    assert "[[" not in out
    assert len(out.split()) == 5  # 2 + "and" + 2


def test_referenced_lists_the_pools_a_post_needs():
    assert hashtags.referenced("a [[tags:tech:2]] b [[tags:VN]]") == {"tech", "vn"}


def test_text_without_placeholders_is_untouched():
    assert hashtags.expand("no tags here", POOLS, random.Random(1)) == "no tags here"


def test_combination_factor_counts_ordered_selections():
    # P(6,3) = 6*5*4 = 120
    assert hashtags.combination_factor("[[tags:tech:3]]", POOLS) == 120


def test_combination_factor_multiplies_across_placeholders():
    # P(6,2)=30, P(3,2)=6  -> 180
    assert hashtags.combination_factor("[[tags:tech:2]][[tags:vn:2]]", POOLS) == 180


def test_a_hashtag_pool_beats_spintax_branches_at_lowering_collisions():
    """Day la ly do dung tui rut ngau nhien thay vi mot khoi hashtag co dinh."""
    assert hashtags.combination_factor("[[tags:tech:3]]", POOLS) > 100


def test_no_placeholders_means_factor_of_one():
    assert hashtags.combination_factor("plain text", POOLS) == 1
