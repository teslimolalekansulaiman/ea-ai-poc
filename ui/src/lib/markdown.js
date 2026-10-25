// Minimal markdown -> HTML: headings, bold, inline code, lists, paragraphs, and
// [block:id] citations -> clickable spans (data-cite). The <Markdown> component wires
// clicks on .cite to the citation modal.
function esc(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
}
// A block id is "<document id>:<ordinal>[#chunk]" and the document id is the uploaded file's
// name, so it may contain spaces, underscores, dots and brackets (not only "03-data"). Only
// letters/digits and those marks are allowed, so an id can never carry markup into data-cite.
const CITE_ONE = '[\\p{L}\\p{N}_][\\p{L}\\p{N}_ \\-.()]*:\\d+(?:#\\d+)?'
const CITE = new RegExp('\\[(' + CITE_ONE + '(?:\\s*,\\s*' + CITE_ONE + ')*)\\]', 'gu')

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
