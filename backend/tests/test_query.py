from app.query import DEFINITION, METHOD, NUMERIC, RESULT, classify, rewrite, sections


def test_classify_numeric():
    assert classify("LASSO 模型的 R² 是多少？") == NUMERIC


def test_classify_method():
    assert classify("论文使用了哪些主要建模方法？") == METHOD


def test_classify_definition():
    assert classify("LASSO 是什么？") == DEFINITION


def test_classify_result():
    assert classify("实验结果怎么样？") == RESULT


def test_rewrite_contains_original_and_expansion():
    query = rewrite("R² 是多少？", NUMERIC)
    assert "R² 是多少" in query
    assert "数值" in query


def test_section_filter_exists_for_method():
    assert sections(METHOD)
