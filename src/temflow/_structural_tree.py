"""Exact prospective uncertainty profiles for nested aggregate measurements.

Structural kernel used by TEM-FLOW v1.0.0, revision 2026-10-01. A tree represents
nested accounting groups, NOT a replacement for a physical route network.
The mathematical algorithm uses max-flow/min-cut and tree dynamic programming.
No claim of literature priority is made for those established ingredients.
"""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class Record:
    id: str
    edge: int
    error: float

class NestedLedger:
    def __init__(self,nodes,edges,terminals,records,mass):
        self.nodes=tuple(nodes)
        self.n=len(nodes)
        if self.n<1 or len(set(nodes))!=self.n:raise ValueError('Unique nonempty node list required')
        self.edges=tuple(tuple(e) for e in edges)
        self.mass=float(mass)
        if not math.isfinite(self.mass) or self.mass<0:raise ValueError('Finite nonnegative exact total required')
        self.adj=[[] for _ in nodes]
        if len(edges)!=self.n-1:raise ValueError('Accounting graph must be a tree')
        for ei,(u,v) in enumerate(self.edges):
            if not(0<=u<self.n and 0<=v<self.n) or u==v:raise ValueError('Invalid edge')
            self.adj[u].append((v,ei));self.adj[v].append((u,ei))
        parent=[-1]*self.n;parent[0]=0;order=[0]
        for v in order:
            for w,_ in self.adj[v]:
                if w==parent[v]:continue
                if parent[w]!=-1:raise ValueError('Cycle in accounting graph')
                parent[w]=v;order.append(w)
        if len(order)!=self.n:raise ValueError('Disconnected accounting graph')
        self.parent=parent;self.order=order
        self.terminals=tuple(sorted(terminals));self.terminal_set=set(terminals)
        if not self.terminals or len(self.terminal_set)!=len(self.terminals):raise ValueError('Terminals must be nonempty and unique')
        if any(not 0<=v<self.n or len(self.adj[v])>1 for v in self.terminals):
            raise ValueError('Commodity destinations must be leaves')
        self.records=tuple(records)
        if len({r.id for r in records})!=len(records):raise ValueError('Duplicate record identities')
        self.by_edge=[[] for _ in edges]
        for r in records:
            if not 0<=r.edge<len(edges) or not math.isfinite(r.error) or r.error<0:raise ValueError('Invalid record')
            self.by_edge[r.edge].append(r)
        for a in self.by_edge:a.sort(key=lambda r:(r.error,r.id))

    def profiles(self,r):
        if not isinstance(r,int) or r<0:raise ValueError('Nonnegative integer failure allowance required')
        M=self.mass;zero=[0.]*(r+1);full=[M]*(r+1)
        caps=[[min(M,2*a[k].error) if k<len(a) else M for k in range(r+1)] for a in self.by_edge]
        messages={};operations=0
        def combine(a,b):
            nonlocal operations
            out=[]
            for k in range(r+1):
                out.append(min(M,max(a[j]+b[k-j] for j in range(k+1))))
                operations+=k+1
            return out
        def edge_apply(e,b):
            nonlocal operations
            out=[]
            for k in range(r+1):
                upto=min(k,len(self.by_edge[e]))
                out.append(max(min(caps[e][j],b[k-j]) for j in range(upto+1)))
                operations+=upto+1
            return out
        for v in reversed(self.order[1:]):
            par=self.parent[v]
            b=full[:] if v in self.terminal_set else zero[:]
            for w,e in self.adj[v]:
                if w!=par:b=combine(b,messages[(v,w)])
                else:parent_e=e
            messages[(par,v)]=edge_apply(parent_e,b)
        for v in self.order:
            neighbors=self.adj[v]
            if v in self.terminal_set:
                for w,e in neighbors:messages[(w,v)]=edge_apply(e,full)
                continue
            incoming=[messages[(v,w)] for w,e in neighbors]
            prefix=[zero[:]]
            for a in incoming:prefix.append(combine(prefix[-1],a))
            suffix=[None]*(len(incoming)+1);suffix[-1]=zero[:]
            for i in range(len(incoming)-1,-1,-1):suffix[i]=combine(incoming[i],suffix[i+1])
            for i,(w,e) in enumerate(neighbors):
                b=combine(prefix[i],suffix[i+1])
                messages[(w,v)]=edge_apply(e,b)
        result={v:(messages[(v,self.adj[v][0][0])][:] if self.adj[v] else zero[:]) for v in self.terminals}
        return {'widths':result,'messages':messages,'caps':caps,'operations':operations,'r':r}

    def witness(self,target,r,calculation=None):
        """Return erased record IDs, two nonnegative mass-balanced flows, common readings."""
        if target not in self.terminal_set:raise ValueError('Target must be a terminal')
        calc=calculation or self.profiles(r)
        if calc['r']<r:raise ValueError('Profile budget too small')
        M=self.mass;msgs=calc['messages'];caps=calc['caps']
        erased=set()
        if not self.adj[target]:return {'erased':[],'x':[M],'x_prime':[M],'width':0.,'common_readings':[]}
        first,ei=self.adj[target][0];stack=[(target,first,ei,r)]
        while stack:
            u,v,e,k=stack.pop()
            children=[(w,ee) for w,ee in self.adj[v] if w!=u]
            tables=[[0.]*(k+1)];choices=[]
            if v in self.terminal_set:
                b=[M]*(k+1)
            else:
                for w,ee in children:
                    old=tables[-1];a=msgs[(v,w)];new=[];choice=[]
                    for q in range(k+1):
                        jj=max(range(q+1),key=lambda j:old[q-j]+a[j])
                        new.append(min(M,old[q-jj]+a[jj]));choice.append(jj)
                    tables.append(new);choices.append(choice)
                b=tables[-1]
            j=max(range(min(k,len(self.by_edge[e]))+1),key=lambda z:min(caps[e][z],b[k-z]))
            erased.update(rec.id for rec in self.by_edge[e][:j])
            if v not in self.terminal_set:
                remaining=k-j
                for i in range(len(children)-1,-1,-1):
                    take=choices[i][remaining];w,ee=children[i]
                    stack.append((v,w,ee,take));remaining-=take
        # Recover a feasible transfer using the surviving capacities.
        edgecap=[min([M]+[2*rec.error for rec in a if rec.id not in erased]) for a in self.by_edge]
        parent={target:target};pe={};order=[target]
        for v in order:
            for w,e in self.adj[v]:
                if w==parent[v]:continue
                parent[w]=v;pe[w]=e;order.append(w)
        capacity={}
        for v in reversed(order[1:]):
            b=M if v in self.terminal_set else min(M,sum(capacity[w] for w,e in self.adj[v] if w!=parent[v]))
            capacity[v]=min(edgecap[pe[v]],b)
        width=min(M,sum(capacity[w] for w,e in self.adj[target]))
        allocations={v:0. for v in self.terminals};stack=[(target,width)]
        while stack:
            v,amount=stack.pop()
            if v in self.terminal_set and v!=target:allocations[v]+=amount;continue
            for w,e in self.adj[v]:
                if w==parent[v]:continue
                take=min(amount,capacity[w]);stack.append((w,take));amount-=take
            if abs(amount)>1e-7:raise AssertionError('Transfer reconstruction failed')
        x=[M if v==target else 0. for v in self.terminals]
        xp=[M-width if v==target else allocations[v] for v in self.terminals]
        # Aggregate midpoint masses in linear time; do not materialize a
        # records-by-destinations matrix merely to report the shared readings.
        subtree=[0.]*self.n
        for v,a,b in zip(self.terminals,x,xp):subtree[v]=(a+b)/2
        for v in reversed(self.order[1:]):subtree[self.parent[v]]+=subtree[v]
        ys=[]
        for rec in self.records:
            u,v=self.edges[rec.edge]
            child=v if self.parent[v]==u else u
            ys.append(subtree[child])
        assert len(erased)<=r
        assert abs(width-calc['widths'][target][r])<1e-7
        return {'erased':sorted(erased),'x':x,'x_prime':xp,'width':width,'common_readings':ys}

    def measurement_matrix(self):
        """Subtree sums relative to node 0; complementary sides are equivalent."""
        descendants=[set() for _ in self.nodes]
        index={v:i for i,v in enumerate(self.terminals)}
        for v in reversed(self.order):
            if v in index:descendants[v].add(index[v])
            if v!=0:descendants[self.parent[v]].update(descendants[v])
        rows=[]
        for rec in self.records:
            u,v=self.edges[rec.edge]
            child=v if self.parent[v]==u else u
            rows.append([int(i in descendants[child]) for i in range(len(self.terminals))])
        return rows

    def payload(self):
        return {'nodes':self.nodes,'edges':self.edges,'terminals':self.terminals,
                'records':[{'id':r.id,'edge':r.edge,'error':r.error} for r in self.records], 'mass':self.mass}

def from_payload(p):
    return NestedLedger(p['nodes'],p['edges'],p['terminals'],[Record(**r) for r in p['records']],p['mass'])

def example():
    # R contains G and U; G contains A and B. B has two distinct readings.
    return NestedLedger(['R','G','A','B','U'],[(0,1),(1,2),(1,3),(0,4)],[2,3,4],
                        [Record('G-total',0,1),Record('B-precise',2,1),
                         Record('B-backup',2,2),Record('U-total',3,1)],100)
