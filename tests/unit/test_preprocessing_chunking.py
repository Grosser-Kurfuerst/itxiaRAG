import pytest

from contracts.errors import DomainError
from contracts.types import evidence_input
from ingestion.chunking import BudgetChunker, TokenizerCounter, Utf8ByteCounter
from ingestion.preprocessing import SemanticContext, SemanticEvidence


def unit(body, *, title="笔记本", atomic=False):
    return SemanticContext("machine", title, body, [SemanticEvidence("body", body, atomic=atomic)])


def test_chunks_count_full_model_input_preserve_text_and_have_exact_parent_offsets():
    body = "配置段落。\n\n优点一：续航好。优点二：噪音低。\n\n注意价格变化。"
    chunker = BudgetChunker(max_input_units=48)
    parent, = chunker.chunk([unit(body)])
    assert len(parent.children) > 1
    assert "".join(child.body for child in parent.children) == body
    for child in parent.children:
        assert len((parent.title + "\n" + child.body).encode()) <= 48
        assert parent.body[child.locator["parent_char_start"]:child.locator["parent_char_end"]] == child.body
    assert len({child.key for child in parent.children}) == len(parent.children)


def test_short_atomic_input_is_unchanged_and_overlong_atomic_input_is_rejected():
    body = "条件：室温25℃。结果：CPU 80℃。"
    chunker = BudgetChunker(max_input_units=100)
    child, = chunker.chunk([unit(body, atomic=True)])[0].children
    assert child.body == body and child.key == "body"
    with pytest.raises(DomainError) as error:
        BudgetChunker(max_input_units=24).chunk([unit(body, atomic=True)])
    assert error.value.code == "SEMANTIC_UNIT_TOO_LARGE"


def test_model_tokenizer_can_replace_default_byte_counter():
    # 合成 tokenizer 每两个字符一 token，验证标题/正文统一经过同一个计数器。
    counter = TokenizerCounter(lambda text: [text[i:i + 2] for i in range(0, len(text), 2)])
    assert Utf8ByteCounter().count("中文") == 6
    assert counter.count("中文") == 1
    chunker = BudgetChunker(max_input_units=6, counter=counter)
    parent, = chunker.chunk([unit("abcdefghijklmno", title="A")])
    assert all(counter.count(parent.title + "\n" + child.body) <= 6 for child in parent.children)
    assert "".join(child.body for child in parent.children) == parent.body


def test_character_contract_still_applies_with_compacting_tokenizer():
    counter = TokenizerCounter(lambda text: [text])
    parent, = BudgetChunker(max_input_units=10, counter=counter).chunk([unit("x" * 33000, title="A")])
    assert len(parent.children) == 2
    assert max(len(child.body) for child in parent.children) <= 32000


def test_impossible_title_and_chunk_count_limit_fail_before_embedding():
    with pytest.raises(DomainError, match="标题"):
        BudgetChunker(max_input_units=2).chunk([unit("正文")])
    with pytest.raises(DomainError, match="100 个子块"):
        BudgetChunker(max_input_units=3).chunk([unit("x" * 101, title="A")])
    with pytest.raises(ValueError, match="正整数"):
        BudgetChunker(max_input_units=True)


def test_text_without_sentence_boundaries_splits_at_line_breaks():
    body = "| 项目 | 值 |\n| --- | --- |\n| 内存 | 16GB |\n| 硬盘 | 512GB |\n| 屏幕 | 165Hz |"
    parent, = BudgetChunker(max_input_units=40).chunk([unit(body, title="A")])
    assert len(parent.children) > 1
    assert "".join(child.body for child in parent.children) == body
    for child in parent.children:
        assert all(line.startswith("|") and line.endswith("|") for line in child.body.splitlines())


def assert_valid_split(parent, budget):
    for child in parent.children:
        assert len(evidence_input(parent.title, child.body, child.retrieval_prefix).encode()) <= budget
        assert parent.body[child.locator["parent_char_start"]:child.locator["parent_char_end"]] == child.body
    assert "".join(child.body for child in parent.children) == parent.body


TABLE = "| 项目 | 值 |\n| --- | --- |\n" + "".join(f"| 项目{i} | 数值{i}GB。 |\n" for i in range(12))


def test_split_rejects_breakpoints_too_close_to_start_and_balances_tail():
    # 只有开头一个段落边界时，不生成只含“配置”的子块。
    parent, = BudgetChunker(max_input_units=200).chunk([unit("配置\n\n" + TABLE)])
    assert_valid_split(parent, 200)
    assert parent.children[0].body.startswith("配置\n\n| 项目 | 值 |\n| --- | --- |\n| 项目0")
    # 刚超预算的长段按剩余长度均分，不留下只有末句的极短尾块。
    body = "这台电脑适合轻办公和学习使用。" * 9 + "适合学生。"
    parent, = BudgetChunker(max_input_units=330).chunk([unit(body)])
    assert_valid_split(parent, 330)
    lengths = [len(child.body) for child in parent.children]
    assert len(lengths) == 2 and min(lengths) >= max(lengths) / 2


def test_table_split_keeps_rows_whole_and_adds_header_only_to_model_input():
    parent, = BudgetChunker(max_input_units=160).chunk([unit(TABLE)])
    assert_valid_split(parent, 160)
    first, *rest = parent.children
    assert rest and first.retrieval_prefix == "" and first.body.startswith("| 项目 | 值 |")
    for child in rest:
        # 单元格中的句号不作为断点；后续子块正文从数据行开始，表头只进入编码文本。
        assert child.retrieval_prefix == "| 项目 | 值 |\n| --- | --- |"
        assert child.body.startswith("| 项目") and "| --- |" not in child.body
    for child in parent.children:
        assert all(line.startswith("|") and line.endswith("|") for line in child.body.splitlines())


def test_table_header_is_dropped_when_it_cannot_fit_with_any_row():
    body = "| 很长很长的列名甲 | 很长很长的列名乙 |\n| a | 1 |\n| b | 2 |\n| c | 3 |"
    parent, = BudgetChunker(max_input_units=60).chunk([unit(body, title="A")])
    assert_valid_split(parent, 60)
    assert all(child.retrieval_prefix == "" for child in parent.children)


def test_whitespace_and_utf8_split_do_not_lose_or_damage_text():
    body = "第一行  \n第二行🙂继续，没有句号" * 20
    parent, = BudgetChunker(max_input_units=60).chunk([unit(body, title="A")])
    assert "".join(child.body for child in parent.children) == body
    assert all(child.body.encode().decode() == child.body for child in parent.children)
