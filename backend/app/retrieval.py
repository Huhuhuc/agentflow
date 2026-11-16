"""Retrieval ranking and model-fingerprint primitives shared by offline and business paths."""
import hashlib
from pathlib import Path

MODEL_FILES = ('config.json', 'config_sentence_transformers.json', 'model.safetensors',
               'modules.json', 'sentence_bert_config.json', 'special_tokens_map.json',
               'tokenizer.json', 'tokenizer_config.json', 'vocab.txt', '1_Pooling/config.json')
QUERY_PREFIX = '为这个句子生成表示以用于检索相关文章：'


def model_fingerprint(path):
    root = Path(path).resolve()
    digest = hashlib.sha256()
    for name in MODEL_FILES:
        file = (root / name).resolve()
        if not file.is_relative_to(root) or not file.is_file():
            raise ValueError('Missing or unsafe model file: '+name)
        digest.update(name.encode())
        with file.open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                digest.update(block)
    return 'sha256:'+digest.hexdigest()


def token_chunks(text, tokenizer, max_tokens, overlap=32):
    """Offsets refer to original text; re-encode each slice to forbid truncation."""
    capacity = max_tokens-tokenizer.num_special_tokens_to_add(pair=False)
    if capacity < 2 or not 0 <= overlap < capacity:
        raise ValueError('Invalid token budget')
    offsets = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, truncation=False)['offset_mapping']
    chunks=[]; cursor=0
    while cursor < len(offsets):
        end=min(cursor+capacity,len(offsets))
        start_char=0 if cursor==0 else offsets[cursor][0]
        while end>cursor:
            end_char=len(text) if end==len(offsets) else offsets[end-1][1]
            piece=text[start_char:end_char]
            if len(tokenizer(piece,truncation=False)['input_ids'])<=max_tokens:break
            end-=1
        if end==cursor:raise ValueError('Cannot fit token into chunk')
        chunks.append({'start':start_char,'end':end_char,'text':piece})
        if end==len(offsets):break
        cursor=max(cursor+1,end-overlap)
    return chunks


def lexical_rank(query, chunks):
    query=query.lower()
    grams={query[i:i+2] for i in range(len(query)-1) if query[i:i+2].strip()}
    return sorted(range(len(chunks)),key=lambda i:(-sum(g in chunks[i]['text'].lower() for g in grams),chunks[i]['id']))


def vector_rank(query_vector, vectors, chunks):
    if len(vectors)!=len(chunks) or any(len(v)!=len(query_vector) for v in vectors):
        raise ValueError('Vector dimensions do not match')
    return sorted(range(len(vectors)),key=lambda i:(-sum(a*b for a,b in zip(query_vector,vectors[i])),chunks[i]['id']))


def fuse(*rankings, k=60):
    scores={}
    for ranking in rankings:
        for position,index in enumerate(ranking[:20],1):scores[index]=scores.get(index,0)+1/(k+position)
    return sorted(scores,key=lambda i:(-scores[i],i))
