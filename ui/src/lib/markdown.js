// Minimal markdown -> HTML: headings, bold, inline code, lists, paragraphs, and
// [block:id] citations -> clickable spans (data-cite). The <Markdown> component wires
// clicks on .cite to the citation modal.
function esc(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
}
const CITE = /\[([0-9A-Za-z][0-9A-Za-z-]*:\d+(?:#\d+)?(?:\s*,\s*[0-9A-Za-z][0-9A-Za-z-]*:\d+(?:#\d+)?)*)\]/g

export function mdToHtml(md) {
  md = esc(md)
  md = md.replace(CITE, (m, ids) =>
    ids.split(/\s*,\s*/).map(id => `<span class="cite" data-cite="${id}">${id}</span>`).join(' '))
  md = md.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<span class="mono">$1</span>')
  const lines = md.split(/\n/)
  let html = '', inList = false
  for (const ln of lines) {
    if (/^#{1,6}\s/.test(ln)) {
      if (inList) { html += '</ul>'; inList = false }
      const lvl = ln.match(/^#+/)[0].length
      const tag = lvl <= 1 ? 'h2' : 'h3'
      html += `<${tag}>${ln.replace(/^#+\s/, '')}</${tag}>`
    } else if (/^\s*[-*]\s/.test(ln)) {
      if (!inList) { html += '<ul>'; inList = true }
      html += `<li>${ln.replace(/^\s*[-*]\s/, '')}</li>`
    } else if (ln.trim() === '') {
      if (inList) { html += '</ul>'; inList = false }
    } else {
      if (inList) { html += '</ul>'; inList = false }
      html += `<p>${ln}</p>`
    }
  }
  if (inList) html += '</ul>'
  return html
}
