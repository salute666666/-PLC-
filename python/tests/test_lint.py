from delta_isp_mcp.lint.st_check import check_st


def codes(code: str) -> set[str]:
    return {issue.code for issue in check_st(code)}


def test_balanced_code_has_no_errors():
    issues = check_st("IF A THEN\nB := TRUE;\nEND_IF;")
    assert [i for i in issues if i.severity == "error"] == []


def test_unbalanced_if():
    assert "UNBALANCED" in codes("IF A THEN\nB := TRUE;")


def test_fullwidth_punctuation():
    assert "FULLWIDTH" in codes("A ＝ 1；")


def test_assignment_warning():
    assert "ASSIGN_EQ" in codes("A = 1;")


def test_multiline_comment_is_ignored():
    issues = check_st("(* this is\n   a comment *)\nA := 1;")
    assert [i for i in issues if i.severity == "error"] == []


def test_non_gbk_character():
    assert "NON_GBK" in codes("A := '😀';")
