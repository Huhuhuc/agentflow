"""Real local embeddings, frozen data, no chat/API generation costs.

Run from backend: python -m evaluation.retrieval_benchmark --model-path PATH --output NEW.json
"""
import argparse
import hashlib
import json
import time
import platform
from pathlib import Path
from importlib.metadata import version
from app.index_worker import LocalEmbedder
from app.retrieval import model_fingerprint, lexical_rank, vector_rank, fuse
from evaluation.retrieval_abstention import calibrate_threshold, evaluate_threshold


def lexical_scores(query, chunks):
    query=query.lower()
    grams={query[i:i+2] for i in range(len(query)-1) if query[i:i+2].strip()}
    return [sum(g in chunk['text'].lower() for g in grams) for chunk in chunks]


def hybrid_scores(lexical, dense, size):
    scores=[0.0]*size
    for ranking in (lexical,dense):
        for position,index in enumerate(ranking[:20],1):scores[index]+=1/(60+position)
    return scores


def run(path, output):
    if output.exists():raise ValueError('Refusing to overwrite an experiment')
    dataset=Path(__file__).with_name('retrieval-cases.json')
    data=json.loads(dataset.read_text(encoding='utf-8'))
    started=time.perf_counter()
    fingerprint=model_fingerprint(path)
    embedder=LocalEmbedder(path,fingerprint)
    load_seconds=time.perf_counter()-started
    chunks=[]
    for group in data['groups']:
        if group['text']:
            for i,chunk in enumerate(embedder.chunks(group['text'])):
                chunks.append({**chunk,'id':group['id']+':'+str(i),'group':group['id']})
    start=time.perf_counter()
    vectors=embedder([c['text'] for c in chunks],fingerprint)
    document_seconds=time.perf_counter()-start
    rows=[]
    for group in data['groups']:
        for number,query in enumerate(group['queries']):
            start=time.perf_counter()
            q=embedder.queries([query])[0]
            embedding_ms=(time.perf_counter()-start)*1000
            lex=lexical_rank(query,chunks);dense=vector_rank(q,vectors,chunks)
            lex_values=lexical_scores(query,chunks)
            dense_values=[sum(a*b for a,b in zip(q,vector)) for vector in vectors]
            hybrid_values=hybrid_scores(lex,dense,len(chunks))
            row={'id':group['id']+':'+str(number),'split':group['split'],'query':query,
                 'answerable':group['text'] is not None,'query_embedding_ms':round(embedding_ms,3),'strategies':{}}
            for name,ranking,scores in [('lexical',lex,lex_values),('vector',dense,dense_values),('hybrid',fuse(lex,dense),hybrid_values)]:
                top=ranking[:5]
                matches=[i+1 for i,index in enumerate(top) if chunks[index]['group']==group['id']]
                row['strategies'][name]={'ids':[chunks[i]['id'] for i in top],
                    'hit_at_5':bool(matches) if row['answerable'] else None,
                    'reciprocal_rank':1/min(matches) if matches else 0 if row['answerable'] else None}
                row['strategies'][name]['top_score']=scores[ranking[0]]
                row['strategies'][name]['top1_correct']=bool(row['answerable'] and chunks[ranking[0]]['group']==group['id'])
            rows.append(row)
    summary={}
    for split in ('dev','test'):
        selected=[r for r in rows if r['split']==split and r['answerable']]
        summary[split]={s:{'answerable_tasks':len(selected),
            'hit_at_5':sum(r['strategies'][s]['hit_at_5'] for r in selected)/len(selected),
            'mrr_at_5':sum(r['strategies'][s]['reciprocal_rank'] for r in selected)/len(selected)}
            for s in ('lexical','vector','hybrid')}
    abstention={}
    for strategy in ('lexical','vector','hybrid'):
        dev=[{'answerable':r['answerable'], 'top_score':r['strategies'][strategy]['top_score'],
              'top1_correct':r['strategies'][strategy]['top1_correct']} for r in rows if r['split']=='dev']
        test=[{'answerable':r['answerable'], 'top_score':r['strategies'][strategy]['top_score'],
               'top1_correct':r['strategies'][strategy]['top1_correct']} for r in rows if r['split']=='test']
        calibrated=calibrate_threshold(dev)
        abstention[strategy]={**calibrated, 'test_metrics':evaluate_threshold(test,calibrated['threshold'])}
        for row in rows:
            result=row['strategies'][strategy]
            result['abstain_threshold']=calibrated['threshold']
            result['abstain']=result['top_score'] < calibrated['threshold']
    report={'dataset_sha256':hashlib.sha256(dataset.read_bytes()).hexdigest(),'model_fingerprint':fingerprint,
        'upstream_revision':'7999e1d3359715c523056ef9478215996d62a620',
        'scope':'36 synthetic queries; 30 positive and 6 no-answer probes. Abstention thresholds are selected per strategy on dev by balanced outcome rate, then evaluated once on test. No independent annotation or statistical significance; synthetic labels are author-defined.',
        'baseline':'lexical bigram without business topic gate; not identical to production search_policy',
        'settings':{'rrf_k':60,'top_k':5,'query_instruction':'BGE Chinese retrieval prefix','normalized':True},
        'dependencies':{x:version(x) for x in ('torch','sentence-transformers','transformers')},
        'platform':platform.platform(),'load_seconds':round(load_seconds,3),'document_embedding_seconds':round(document_seconds,3),
        'dimensions':len(vectors[0]),'chunks':chunks,'summary':summary,'abstention':abstention,'rows':rows}
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf-8') as file:json.dump(report,file,ensure_ascii=False,indent=2)
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-path',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();run(args.model_path,args.output)
