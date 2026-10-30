from app.router import Strategy, route


def test_content_question_uses_single():
    decision = route("这篇论文的方法是什么？", 1)
    assert decision.strategy == Strategy.SINGLE


def test_compare_routes_to_compare():
    decision = route("比较这两篇论文的方法和结果", 2)
    assert decision.strategy == Strategy.COMPARE


def test_compare_with_one_paper_clarifies():
    decision = route("比较这两篇论文的方法", 1)
    assert decision.strategy == Strategy.CLARIFY


def test_innovation_routes_to_innovate():
    decision = route("基于这两篇论文，提出几个创新点", 2)
    assert decision.strategy == Strategy.INNOVATE


def test_definition_routes_to_explain():
    decision = route("LASSO 是什么？", 1)
    assert decision.strategy == Strategy.EXPLAIN


def test_paper_method_question_stays_single():
    decision = route("这篇论文的方法是什么？", 1)
    assert decision.strategy == Strategy.SINGLE


def test_summary_routes_to_summary():
    decision = route("总结一下这篇论文", 1)
    assert decision.strategy == Strategy.SUMMARY


def test_explicit_mode_wins():
    decision = route("这篇论文讲了什么", 2, mode="compare")
    assert decision.strategy == Strategy.COMPARE
