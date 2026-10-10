from math import log
from unittest.mock import Mock, patch
from uuid import UUID

import pytest

from retrieval.bm25 import bm25_scores
from retrieval.keyword import KeywordRetriever
from retrieval.synonyms import SynonymExpander, default_expander
from retrieval.tokenization import tokenize, tokenize_for_search


def test_tokenizer_splits_chinese_and_preserves_identifiers_and_term_frequency():
    assert tokenize('这台笔记本续航怎么样？') == ['笔记本', '续航']
    assert tokenize('RTX 4060 0x80070005 model% C++ C# 14+') == [
        'rtx', '4060', '0x80070005', '80070005', 'model%', 'c++', 'c#', '14+']
    assert tokenize('A14-2025，WIN_11？win_11 USB-C')[:3] == ['a14-2025', '14', '2025']
    assert tokenize('不能开机，没有声音') == ['不能', '开机', '没有', '声音']
    assert tokenize('？！怎么样') == []


def test_tokenizer_adds_model_pieces_so_compact_and_spaced_names_match():
    # 完整型号保留，同时补字母段和数字段；单字符片段不补。
    assert tokenize('air14') == ['air14', 'air', '14']
    assert tokenize('TB14+') == ['tb14+', 'tb', '14+']
    assert tokenize('i7-14650HX') == ['i7-14650hx', '14650', 'hx']
    assert {'air', '14'} <= set(tokenize('来酷Air 14'))
    assert {'14+'} <= set(tokenize('ThinkBook 14+'))


def test_tokenizer_keeps_domain_terms_whole_without_merging_meaningful_words():
    assert tokenize('来酷 斗战者 酷睿 锐龙 双烤') == ['来酷', '斗战者', '酷睿', '锐龙', '双烤']
    # 未收录的复合词仍按普通词语切分，“游戏”可以匹配“游戏本”。
    assert tokenize('游戏本') == ['游戏', '本']


def test_search_mode_adds_sub_words_of_compounds_on_both_sides():
    # 精确模式整体切出复合词，问题“恢复”对不上原文“数据恢复”；搜索模式同时保留整词和子词。
    assert tokenize('数据恢复软件') == ['数据恢复', '软件']
    assert tokenize_for_search('数据恢复软件') == ['数据', '恢复', '数据恢复', '软件']
    assert tokenize_for_search('这台笔记本续航怎么样？') == ['笔记', '笔记本', '续航']
    # 型号与错误码的处理与精确模式相同。
    assert tokenize_for_search('i7-14650HX 0x80070005') == tokenize('i7-14650HX 0x80070005')


def test_synonym_expander_appends_missing_group_members_once():
    expand = SynonymExpander([('流氓软件', '垃圾软件', '捆绑软件')])
    assert expand('流氓软件怎么根治') == '流氓软件怎么根治 垃圾软件 捆绑软件'
    assert expand('流氓软件和垃圾软件') == '流氓软件和垃圾软件 捆绑软件'
    assert expand('电池能用多久') == '电池能用多久'


def test_synonym_expander_reads_groups_and_rejects_short_entries(tmp_path):
    path = tmp_path / 'synonyms.txt'
    path.write_text('# 注释\n\nSSD 固态硬盘  # 行尾注释\n', encoding='utf-8')
    assert SynonymExpander.from_file(path).groups == (('ssd', '固态硬盘'),)
    assert SynonymExpander.from_file(path)('ssd 掉盘') == 'ssd 掉盘 固态硬盘'
    with pytest.raises(ValueError, match='同义词组'):
        SynonymExpander([('固态硬盘',)])
    with pytest.raises(ValueError, match='同义词组'):
        SynonymExpander([('盘', '硬盘')])


def test_bundled_synonym_table_is_valid():
    assert default_expander().groups


def test_keyword_can_tokenize_documents_and_queries_at_different_granularity():
    rows = [(UUID(int=1), UUID(int=10), '数据恢复软件', 'k1')]
    retriever = KeywordRetriever(tokenize_for_search, query_tokenizer=tokenize)
    assert retriever.query_terms('处理器') == ['处理器']
    with patch('retrieval.keyword.scoped_evidence') as scoped:
        scoped.return_value.values_list.return_value = rows
        assert len(retriever.search('怎么恢复', object())) == 1
        assert KeywordRetriever().search('怎么恢复', object()) == []


def test_keyword_expands_only_the_query_and_defaults_to_no_expansion():
    rows = [(UUID(int=1), UUID(int=10), '垃圾软件 清理', 'k1')]
    expand = SynonymExpander([('流氓软件', '垃圾软件')])
    assert KeywordRetriever(str.split).query_terms('流氓软件') == ['流氓软件']
    retriever = KeywordRetriever(str.split, query_expander=expand)
    assert retriever.query_terms('流氓软件') == ['流氓软件', '垃圾软件']
    with patch('retrieval.keyword.scoped_evidence') as scoped, \
            patch('retrieval.keyword.bm25_scores', return_value=[1.0]) as scoring:
        scoped.return_value.values_list.return_value = rows
        assert len(retriever.search('流氓软件', object())) == 1
    assert scoring.call_args.args == ([['垃圾软件', '清理']], ['流氓软件', '垃圾软件'])


def test_bm25_recalls_a_common_term_even_in_a_single_document():
    assert bm25_scores([['续航']], ['续航']) == pytest.approx([log(4 / 3)])
    scores = bm25_scores([['续航'], ['续航'], ['屏幕']], ['续航'])
    assert scores[0] == scores[1] > 0 and scores[2] == 0
    assert bm25_scores([['续航']], ['续航', '续航']) == bm25_scores([['续航']], ['续航'])


def test_bm25_uses_rarity_saturating_frequency_and_document_length():
    scores = bm25_scores([['续航'], ['屏幕'], ['屏幕']], ['续航', '屏幕'])
    assert scores[0] > scores[1] == scores[2] > 0
    scores = bm25_scores([['续航'], ['续航'] * 2, ['屏幕']], ['续航'], b=0)
    assert scores[0] < scores[1] < 2 * scores[0]
    scores = bm25_scores([['续航'], ['续航'] + ['屏幕'] * 20], ['续航'])
    assert scores[0] > scores[1] > 0


@pytest.mark.parametrize('corpus', [[], [[]], [[], []]])
def test_bm25_handles_empty_corpora(corpus):
    assert bm25_scores(corpus, ['续航']) == [0.0] * len(corpus)
    assert bm25_scores(corpus, []) == [0.0] * len(corpus)


def test_keyword_tokenizer_is_replaceable_and_ranking_precedes_limit():
    scope, parent = object(), UUID(int=10)
    tokenizer = Mock(side_effect=lambda text: text.split())
    rows = [(UUID(int=2), parent, 'battery screen', 'k2'),
            (UUID(int=1), parent, 'battery', 'k1'),
            (UUID(int=3), parent, 'keyboard', 'k3')]
    with patch('retrieval.keyword.scoped_evidence') as scoped:
        scoped.return_value.values_list.return_value = rows
        result = KeywordRetriever(tokenizer).search('battery', scope, 1)
    scoped.assert_called_once_with(scope)
    assert tokenizer.call_count == 4
    assert len(result) == 1 and result[0].evidence_id == UUID(int=1)
    assert result[0].context_id == parent and result[0].ranks == {'keyword': 1}


def test_keyword_excludes_nonmatches_and_orders_ties_by_stable_key():
    parent = UUID(int=10)
    # 稳定键与 id 顺序相反：同分时按导入后不变的稳定键排序，不依赖随机生成的 id。
    rows = [(UUID(int=1), parent, '续航', 'wechat:b#context-x#evidence-1'),
            (UUID(int=2), parent, '续航', 'wechat:a#context-x#evidence-1'),
            (UUID(int=3), parent, '屏幕', 'wechat:c#context-x#evidence-1')]
    with patch('retrieval.keyword.scoped_evidence') as scoped:
        scoped.return_value.values_list.return_value = rows
        result = KeywordRetriever().search('续航怎么样', object())
    assert [item.evidence_id for item in result] == [UUID(int=2), UUID(int=1)]
    assert [item.ranks for item in result] == [{'keyword': 1}, {'keyword': 2}]
    assert [item.stable_key for item in result] == ['wechat:a#context-x#evidence-1', 'wechat:b#context-x#evidence-1']


def test_keyword_empty_query_does_not_read_the_database():
    with patch('retrieval.keyword.scoped_evidence') as scoped:
        assert KeywordRetriever().search('？！', object()) == []
    scoped.assert_not_called()


def test_keyword_threshold_preserves_positive_matches_and_original_scores():
    parent = UUID(int=10)
    rows = [(UUID(int=i), parent, 'battery', f'k{i}') for i in range(1, 5)]
    with patch('retrieval.keyword.scoped_evidence') as scoped, \
            patch('retrieval.keyword.bm25_scores', return_value=[0, .4, .8, 1.2]) as scoring:
        scoped.return_value.values_list.return_value = rows
        result = KeywordRetriever(str.split, min_bm25=.8).search('battery', object())
    assert len(scoring.call_args.args[0]) == 4  # 过滤前仍统计完整 Scope 语料。
    assert [item.evidence_id for item in result] == [UUID(int=4), UUID(int=3)]
    assert [item.ranks for item in result] == [{'keyword': 1}, {'keyword': 2}]
    assert [item.route_scores for item in result] == [{'keyword': 1.2}, {'keyword': .8}]
    assert all(item.score_kind == 'bm25' for item in result)


@pytest.mark.parametrize('threshold', [-.1, float('nan'), float('inf')])
def test_keyword_rejects_invalid_thresholds(threshold):
    with pytest.raises(ValueError, match='min_bm25'):
        KeywordRetriever(min_bm25=threshold)


def test_composition_root_switches_keyword_analysis(settings, embedder):
    from config import components
    settings.RETRIEVAL_KEYWORD_SEARCH_MODE, settings.RETRIEVAL_KEYWORD_SYNONYMS = "off", False
    keyword = components.recall_collector(embedder).retrievers[0]
    assert (keyword.tokenize, keyword.tokenize_query, keyword.query_expander) == (tokenize, tokenize, None)
    keyword = components.recall_collector(embedder, search_mode="document", synonyms=True).retrievers[0]
    assert (keyword.tokenize, keyword.tokenize_query) == (tokenize_for_search, tokenize)
    assert keyword.query_expander is default_expander()
    keyword = components.recall_collector(embedder, search_mode="both").retrievers[0]
    assert keyword.tokenize_query is tokenize_for_search
