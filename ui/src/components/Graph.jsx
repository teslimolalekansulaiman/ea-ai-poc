import { useMemo } from 'react'
import { ReactFlow, Background, Controls, MiniMap, Handle, Position, MarkerType } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import dagre from '@dagrejs/dagre'

const DOMV = { Motivation: '--l-strategy', Business: '--l-business', Data: '--l-application', Application: '--l-application', Technology: '--l-technology', Realization: '--l-security', Other: '--fg-muted' }
const cvar = (d) => `var(${DOMV[d] || '--fg-muted'})`
const resolved = (d) => { try { return getComputedStyle(document.documentElement).getPropertyValue(DOMV[d] || '--fg-muted').trim() || '#888' } catch { return '#888' } }

// A boxed architecture node: coloured domain stripe + name + type.
function EANode({ data }) {
  return (
    <div className={'eanode' + (data.member ? '' : ' ctx')} style={{ borderColor: cvar(data.domain) }}>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <span className="stripe" style={{ background: cvar(data.domain) }} />
      <div className="lbl"><div className="nm">{data.label}</div><div className="ty">{data.type}</div></div>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  )
}
const nodeTypes = { ea: EANode }
const W = 184, H = 52

function layout(nodes, edges) {
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'LR', nodesep: 26, ranksep: 95, marginx: 20, marginy: 20 })
  nodes.forEach((n) => g.setNode(n.id, { width: W, height: H }))
  edges.forEach((e) => g.setEdge(e.source, e.target))
  dagre.layout(g)
  return nodes.map((n) => {
    const p = g.node(n.id)
    return { id: n.id, type: 'ea', position: { x: p.x - W / 2, y: p.y - H / 2 },
             data: { label: n.name, type: n.type, domain: n.domain, member: n.member !== 0 } }
  })
}

export default function Graph({ nodes, edges, onNodeClick }) {
  const { rfNodes, rfEdges } = useMemo(() => {
    const ids = new Set(nodes.map((n) => n.id))
    const es = edges.filter((e) => ids.has(e.source) && ids.has(e.target))
    return {
      rfNodes: layout(nodes, es),
      rfEdges: es.map((e, i) => ({
        id: 'e' + i, source: e.source, target: e.target, label: e.relation,
        markerEnd: { type: MarkerType.ArrowClosed },
        labelStyle: { fontSize: 9, fill: 'var(--fg-faint)' },
        labelBgStyle: { fill: 'var(--surface)' },
        style: { stroke: 'var(--border-strong)' },
      })),
    }
  }, [nodes, edges])

  return (
    <div style={{ width: '100%', height: 560 }}>
      <ReactFlow key={rfNodes.length + '-' + rfEdges.length} nodes={rfNodes} edges={rfEdges}
        nodeTypes={nodeTypes} fitView minZoom={0.15} proOptions={{ hideAttribution: true }}
        onNodeClick={(_, n) => onNodeClick && onNodeClick(n.id)}>
        <Background gap={16} color="var(--border)" />
        <Controls showInteractive={false} />
        <MiniMap nodeColor={(n) => resolved(n.data?.domain)} pannable zoomable />
      </ReactFlow>
    </div>
  )
}
