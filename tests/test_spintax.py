from seeding.content.spintax import combinations, content_hash, expand, rng_for


def test_chooses_one_branch():
    assert expand("{a|b|c}", rng_for("seed")) in {"a", "b", "c"}


def test_nested_blocks():
    out = expand("{x{1|2}|y{3|4}}", rng_for("seed"))
    assert out in {"x1", "x2", "y3", "y4"}


def test_pipe_inside_nested_block_is_not_a_top_level_split():
    out = expand("{A {p|q} B|C}", rng_for("n"))
    assert out in {"A p B", "A q B", "C"}


def test_plain_text_passes_through():
    assert expand("khong co spintax", rng_for("s")) == "khong co spintax"


def test_same_seed_gives_same_output():
    """Day la tinh chat quan trong nhat: lap ke hoach lai khong doi noi dung."""
    template = "{Chao|Hi} {ban|cac ban}, {hom nay|toi nay} the nao?"
    a = expand(template, rng_for("campaign-1", "account-7"))
    b = expand(template, rng_for("campaign-1", "account-7"))
    assert a == b


def test_different_accounts_diverge():
    template = "{a|b|c|d|e|f|g|h} {1|2|3|4|5|6|7|8}"
    outs = {expand(template, rng_for("campaign-1", f"acc-{i}")) for i in range(20)}
    # Khong doi hoi tat ca khac nhau, chi doi hoi khong bi sup ve mot gia tri.
    assert len(outs) > 10


def test_unclosed_brace_does_not_crash():
    assert expand("mo ma khong dong {a|b", rng_for("s")).startswith("mo ma khong dong ")


def test_content_hash_is_stable_and_distinguishes():
    assert content_hash("t", "b") == content_hash("t", "b")
    assert content_hash("t", "b") != content_hash("t", "b2")


def test_counts_combinations_of_a_flat_template():
    assert combinations("{a|b|c}") == 3
    assert combinations("{a|b} {c|d}") == 4


def test_plain_text_has_exactly_one_combination():
    assert combinations("khong co spintax") == 1


def test_counts_nested_combinations():
    # {x{1|2}|y}  ->  x1, x2, y
    assert combinations("{x{1|2}|y}") == 3


def test_counting_matches_what_expand_can_actually_produce():
    """Con so phai dung, khong phai xap xi - no la co so de canh bao trung bai."""
    template = "{a|b|c} {1|2}"
    produced = {expand(template, rng_for(i)) for i in range(400)}
    assert len(produced) == combinations(template) == 6


def test_a_realistic_template_is_counted():
    template = (
        "{Vua thu|Moi test|Nghich thu} mot cong cu {lap lich|dang bai} {kha hay|khong te|dung duoc}"
    )
    assert combinations(template) == 3 * 2 * 3
