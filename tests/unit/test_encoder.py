from pathlib import Path
from typing import List

import numpy as np
import pytest
import torch
from jina import Document, DocumentArray, Executor
from transform_encoder import TransformerTorchEncoder

_EMBEDDING_DIM = 768


@pytest.fixture(scope='session')
def basic_encoder() -> TransformerTorchEncoder:
    return TransformerTorchEncoder()


def test_config():
    ex = Executor.load_config(str(Path(__file__).parents[2] / 'config.yml'))
    assert ex.pooling_strategy == 'mean'


def test_compute_tokens(basic_encoder: TransformerTorchEncoder):
    tokens = basic_encoder._generate_input_tokens(
        ['hello this is a test', 'and another test']
    )

    assert tokens['input_ids'].shape == (2, 7)
    assert tokens['attention_mask'].shape == (2, 7)


@pytest.mark.parametrize('hidden_seqlen', [4, 8])
def test_compute_embeddings(hidden_seqlen: int, basic_encoder: TransformerTorchEncoder):
    embedding_size = 10
    tokens = basic_encoder._generate_input_tokens(['hello world'])
    hidden_states = tuple(
        torch.zeros(1, hidden_seqlen, embedding_size) for _ in range(7)
    )

    embeddings = basic_encoder._compute_embedding(
        hidden_states=hidden_states, input_tokens=tokens
    )

    assert embeddings.shape == (1, embedding_size)


def test_encoding_cpu():
    enc = TransformerTorchEncoder(device='cpu')
    input_data = DocumentArray([Document(text='hello world')])

    enc.encode(docs=input_data, parameters={})

    assert input_data[0].embedding.shape == (_EMBEDDING_DIM,)


@pytest.mark.gpu
def test_encoding_gpu():
    enc = TransformerTorchEncoder(device='cuda')
    input_data = DocumentArray([Document(text='hello world')])

    enc.encode(docs=input_data, parameters={})

    assert input_data[0].embedding.shape == (_EMBEDDING_DIM,)


@pytest.mark.parametrize(
    'model_name',
    [
        'microsoft/deberta-base',
        'distilbert-base-uncased',
        'mrm8488/longformer-base-4096-finetuned-squadv2',
    ],
)
def test_models(model_name: str):
    encoder = TransformerTorchEncoder(model_name)
    input_data = DocumentArray([Document(text='hello world')])

    encoder.encode(docs=input_data, parameters={})

    assert input_data[0].embedding.shape == (_EMBEDDING_DIM,)


@pytest.mark.parametrize('layer_index', [0, 1, -1])
def test_layer_index(layer_index: int):
    encoder = TransformerTorchEncoder(layer_index=layer_index)
    input_data = DocumentArray([Document(text='hello world')])
    encoder.encode(docs=input_data, parameters={})

    assert input_data[0].embedding.shape == (_EMBEDDING_DIM,)


@pytest.mark.parametrize('pooling_strategy', ['cls', 'mean', 'min', 'max'])
def test_pooling_strategy(pooling_strategy: str):
    encoder = TransformerTorchEncoder(pooling_strategy=pooling_strategy)
    input_data = DocumentArray([Document(text='hello world')])

    encoder.encode(input_data, parameters={})
    assert input_data[0].embedding.shape == (_EMBEDDING_DIM,)


@pytest.mark.parametrize(
    'traversal_paths, counts',
    [
        ('@r', [['@r', 1], ['@c', 0], ['@cc', 0]]),
        ('@c', [['@r', 0], ['@c', 3], ['@cc', 0]]),
        ('@cc', [['@r', 0], ['@c', 0], ['@cc', 2]]),
        ('@cc,r', [['@r', 1], ['@c', 0], ['@cc', 2]]),
    ],
)
def test_traversal_path(
    traversal_paths: str, counts: List, basic_encoder: TransformerTorchEncoder
):
    text = 'blah'
    docs = DocumentArray([Document(id='root1', text=text)])
    docs[0].chunks = [
        Document(id='chunk11', text=text),
        Document(id='chunk12', text=text),
        Document(id='chunk13', text=text),
    ]
    docs[0].chunks[0].chunks = [
        Document(id='chunk111', text=text),
        Document(id='chunk112', text=text),
    ]

    basic_encoder.encode(docs=docs, parameters={'traversal_paths': traversal_paths})
    for path, count in counts:
        embeddings = docs[path].embeddings
        if count != 0:
            assert len([em for em in embeddings if em is not None]) == count
        else:
            assert embeddings is None

@pytest.mark.parametrize('batch_size', [1, 2, 4, 8])
def test_batch_size(basic_encoder: TransformerTorchEncoder, batch_size: int):
    docs = DocumentArray([Document(text='hello there') for _ in range(32)])
    basic_encoder.encode(docs, parameters={'batch_size': batch_size})

    for doc in docs:
        assert doc.embedding.shape == (_EMBEDDING_DIM,)


def test_quality_embeddings(basic_encoder: TransformerTorchEncoder):
    docs = DocumentArray(
        [
            Document(id='A', text='a furry animal that with a long tail'),
            Document(id='B', text='a domesticated mammal with four legs'),
            Document(id='C', text='a type of aircraft that uses rotating wings'),
            Document(id='D', text='flying vehicle that has fixed wings and engines'),
        ]
    )

    basic_encoder.encode(DocumentArray(docs), {})

    # assert semantic meaning is captured in the encoding
    docs.match(docs)
    matches = ['B', 'A', 'D', 'C']
    for i, doc in enumerate(docs):
        assert doc.matches[1].id == matches[i]


def test_bad_batch(basic_encoder):
    docs = DocumentArray([Document(text=f'doc {i}') for i in range(10)])
    docs[5].text = ''
    basic_encoder.encode(docs, parameters={'batch_size': 3})
    assert len(list(filter(lambda d: d.embedding is not None, docs))) == 9
    for idx, d in enumerate(docs):
        if idx != 5:
            assert d.embedding.shape == (_EMBEDDING_DIM,)
