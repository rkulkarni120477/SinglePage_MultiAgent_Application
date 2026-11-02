"""Optional derived Chroma projection. Hash vectors are local lexical features, not semantic embeddings."""
import hashlib
import os
import re

def embedding(text):
    vector=[0.0]*128
    for word in re.findall(r'\w+',text.lower()):
        vector[int(hashlib.sha256(word.encode()).hexdigest()[:8],16)%128]+=1
    norm=sum(x*x for x in vector)**0.5 or 1
    return [x/norm for x in vector]

def collection():
    if not os.getenv('CHROMA_HOST'):
        raise RuntimeError('Chroma is not configured. Start the optional compose services and set CHROMA_HOST=127.0.0.1.')
    import chromadb
    client=chromadb.HttpClient(host=os.environ['CHROMA_HOST'],port=int(os.getenv('CHROMA_PORT','8001')))
    return client.get_or_create_collection('approved_knowledge_v1',embedding_function=None)

def rebuild(nodes):
    c=collection()
    if nodes:
        c.upsert(ids=[n['id'] for n in nodes],documents=[n['label'] for n in nodes],embeddings=[embedding(n['label']) for n in nodes],metadatas=[{'node_type':n['node_type'],'status':n['status']} for n in nodes])
    return {'projected':len(nodes),'embedding':'128-dimensional deterministic lexical hash; replace with a semantic embedding provider for production'}

def search(query):
    c=collection()
    if not c.count(): return {'ids':[],'documents':[]}
    return c.query(query_embeddings=[embedding(query)],n_results=min(c.count(),10))
