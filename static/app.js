const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
let allProducts = [];
let graphNetwork = null;
const categoryDefaults = ['Electronics', 'Stationery', 'Furniture'];

async function api(url, options = {}) {
  const response = await fetch(url, {headers: {'Content-Type': 'application/json'}, ...options});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}
function toast(message, error = false) {
  const el = $('#toast'); el.textContent = message; el.classList.toggle('error', error); el.classList.remove('hidden');
  clearTimeout(toast.timer); toast.timer = setTimeout(() => el.classList.add('hidden'), 4000);
}
function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function productSymbol(category) { return ({Electronics:'⌁', Stationery:'✎', Furniture:'▱'})[category] || '▤'; }
function quantityMarkup(q) { return `<span class="quantity">${Number(q).toLocaleString()}</span>`; }
function rowMarkup(p, actions = false) {
  const date = p.created_at ? new Date(p.created_at).toLocaleDateString() : '—';
  return `<tr><td><div class="product-cell"><span class="product-symbol">${productSymbol(p.category)}</span>${escapeHtml(p.product)}</div></td><td><span class="category-pill">${escapeHtml(p.category)}</span></td><td>${escapeHtml(p.supplier)}</td><td>${quantityMarkup(p.quantity)}</td>${actions ? `<td>${date}</td><td><div class="action-buttons"><button class="small-action" data-edit="${p.id}">Edit</button><button class="small-action delete" data-delete="${p.id}">Delete</button></div></td>` : '<td></td>'}</tr>`;
}
function renderTables() {
  const recent = [...allProducts].slice(0, 5);
  $('#recent-body').innerHTML = recent.length ? recent.map(p => rowMarkup(p)).join('') : '<tr><td colspan="5" class="empty">No products yet. Add an item or load sample data.</td></tr>';
  const query = ($('#search-input')?.value || '').toLowerCase();
  const cat = $('#filter-category')?.value || ''; const sup = $('#filter-supplier')?.value || '';
  const filtered = allProducts.filter(p => (!cat || p.category === cat) && (!sup || p.supplier === sup) && `${p.product} ${p.supplier} ${p.category}`.toLowerCase().includes(query));
  $('#inventory-body').innerHTML = filtered.length ? filtered.map(p => rowMarkup(p, true)).join('') : '<tr><td colspan="6" class="empty">No matching inventory records.</td></tr>';
  $('#stat-products').textContent = allProducts.length.toLocaleString();
  $('#stat-units').textContent = allProducts.reduce((sum,p) => sum + Number(p.quantity || 0), 0).toLocaleString();
  $('#stat-categories').textContent = new Set(allProducts.map(p=>p.category)).size || 3;
  $('#stat-suppliers').textContent = new Set(allProducts.map(p=>`${p.category}/${p.supplier}`)).size || 6;
}
async function loadProducts() { allProducts = await api('/api/products'); renderTables(); }
async function loadHealth() {
  try {
    const health = await api('/api/health');
    const good = health.mongodb === 'connected' && health.neo4j === 'connected';
    $('#db-status').textContent = `MongoDB ${health.mongodb === 'connected' ? '✓' : '×'} · Neo4j ${health.neo4j === 'connected' ? '✓' : '×'}`;
    $('.pulse').style.background = good ? '#20a77a' : '#e0a441';
  } catch (e) { $('#db-status').textContent = 'Database connection required'; $('.pulse').style.background = '#d65b5b'; }
}
async function loadCategories() {
  try {
    const categories = await api('/api/categories');
    const options = categories.map(c=>`<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
    $('#filter-category').innerHTML = '<option value="">All categories</option>' + options;
    $('#item-category').innerHTML = options;
    await loadSuppliers($('#item-category').value);
  } catch (e) { console.warn(e); }
}
async function loadSuppliers(category) {
  try {
    const suppliers = await api(`/api/suppliers?category=${encodeURIComponent(category)}`);
    const current = $('#item-supplier').value;
    $('#item-supplier').innerHTML = suppliers.map(s=>`<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join('');
    if (suppliers.includes(current)) $('#item-supplier').value = current;
    const filter = $('#filter-supplier').value;
    const allSuppliers = [...new Set(allProducts.map(p=>p.supplier))].sort();
    $('#filter-supplier').innerHTML = '<option value="">All suppliers</option>' + allSuppliers.map(s=>`<option>${escapeHtml(s)}</option>`).join('');
    if (allSuppliers.includes(filter)) $('#filter-supplier').value = filter;
  } catch (e) { console.warn(e); }
}
function showSection(name) {
  $$('.section-page').forEach(s => s.classList.add('hidden'));
  $(`#${name}-section`).classList.remove('hidden');
  $$('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.section === name));
  $('#page-title').textContent = ({overview:'Overview', inventory:'Inventory items', relationships:'Relationship graph'})[name];
  if (name === 'relationships') loadGraph();
  if (name === 'inventory') renderTables();
}
function openModal(product = null) {
  $('#item-form').reset(); $('#form-error').textContent = ''; $('#edit-id').value = product?.id || '';
  $('#modal-title').textContent = product ? 'Edit inventory item' : 'Add inventory item';
  $('#save-button').textContent = product ? 'Save changes' : 'Save item';
  $('#item-modal').classList.remove('hidden');
  if (product) {
    $('#item-category').value = product.category;
    loadSuppliers(product.category).then(() => { $('#item-supplier').value = product.supplier; });
    $('#item-product').value = product.product; $('#item-quantity').value = product.quantity;
  } else { loadSuppliers($('#item-category').value); }
}
function closeModal() { $('#item-modal').classList.add('hidden'); }
async function submitItem(event) {
  event.preventDefault(); $('#form-error').textContent = '';
  const id = $('#edit-id').value;
  const payload = {category: $('#item-category').value, supplier: $('#item-supplier').value, product: $('#item-product').value.trim(), quantity: Number($('#item-quantity').value)};
  const button = $('#save-button'); button.disabled = true; button.textContent = 'Saving…';
  try {
    const result = await api(id ? `/api/products/${id}` : '/api/products', {method: id ? 'PUT' : 'POST', body: JSON.stringify(payload)});
    closeModal(); await loadProducts(); await loadHealth(); toast(result.neo4j_synced === false ? 'Saved to MongoDB, but Neo4j sync needs attention.' : (id ? 'Inventory item updated.' : 'Inventory item added.'));
    if (!$('#relationships-section').classList.contains('hidden')) loadGraph();
  } catch (e) { $('#form-error').textContent = e.message; }
  finally { button.disabled = false; button.textContent = id ? 'Save changes' : 'Save item'; }
}
async function deleteItem(id) {
  const product = allProducts.find(p=>p.id===id); if (!product || !confirm(`Delete “${product.product}” from inventory?`)) return;
  try { const result = await api(`/api/products/${id}`, {method:'DELETE'}); await loadProducts(); toast(result.neo4j_synced === false ? 'Deleted in MongoDB; Neo4j may need cleanup.' : 'Inventory item deleted.'); if (!$('#relationships-section').classList.contains('hidden')) loadGraph(); }
  catch(e) { toast(e.message, true); }
}
async function loadGraph() {
  const message = $('#graph-message'); message.textContent = 'Loading graph…';
  try {
    const data = await api('/api/graph');
    if (!data.nodes.length) { message.textContent = 'No graph data yet. Click “Load sample data” or add an item.'; return; }
    message.textContent = '';
    const colors = {Inventory:{background:'#29243f',border:'#29243f',font:'#fff'},Category:{background:'#e9e3ff',border:'#927ce8',font:'#44347f'},Supplier:{background:'#e5f2ff',border:'#6aa7dd',font:'#245b8d'},Product:{background:'#ddf7ec',border:'#56b995',font:'#176a50'},Quantity:{background:'#fff0dc',border:'#e3a45a',font:'#855019'}};
    const nodes = data.nodes.map(n=>({id:n.id,label:n.kind==='Quantity'?`Qty: ${n.label}`:n.label,shape:n.kind==='Inventory'?'box':'dot',size:n.kind==='Inventory'?25:(n.kind==='Category'?20:15),margin:10,font:{face:'DM Sans',size:12},color:colors[n.kind],title:`${n.kind}\n${n.label}${n.properties?.value !== undefined ? `\nValue: ${n.properties.value}`:''}`}));
    const edges = data.edges.map((e,i)=>({id:`e${i}`,from:e.from,to:e.to,label:e.label,arrows:'to',font:{size:9,align:'middle',color:'#7d8290',strokeWidth:0},color:{color:'#c8cbd6',highlight:'#7557e8'},smooth:{type:'cubicBezier',forceDirection:'horizontal',roundness:.35}}));
    if (graphNetwork) graphNetwork.destroy();
    graphNetwork = new vis.Network($('#graph-canvas'), {nodes:new vis.DataSet(nodes),edges:new vis.DataSet(edges)}, {layout:{hierarchical:{enabled:true,direction:'LR',sortMethod:'directed',levelSeparation:165,nodeSpacing:115,treeSpacing:180,blockShifting:true,edgeMinimization:true}},physics:{enabled:false},interaction:{hover:true,navigationButtons:true,keyboard:true},nodes:{borderWidth:1},edges:{width:1.4,selectionWidth:2}});
    graphNetwork.on('click', params=>{ if(params.nodes.length){const node=data.nodes.find(n=>n.id===params.nodes[0]); if(node) toast(`${node.kind}: ${node.label}${node.properties?.value !== undefined ? ` (quantity ${node.properties.value})`:''}`); }});
  } catch(e) { message.textContent = `${e.message}. Make sure Neo4j is running and sample data is loaded.`; }
}

$$('.nav-item').forEach(btn=>btn.addEventListener('click',()=>showSection(btn.dataset.section)));
$('#top-add').addEventListener('click',()=>openModal()); $('#inventory-add').addEventListener('click',()=>openModal());
$('#open-graph').addEventListener('click',()=>showSection('relationships')); $('#view-all').addEventListener('click',()=>showSection('inventory'));
$('#close-modal').addEventListener('click',closeModal); $('#cancel-modal').addEventListener('click',closeModal); $('#item-form').addEventListener('submit',submitItem);
$('#item-category').addEventListener('change',e=>loadSuppliers(e.target.value));
$('#search-input').addEventListener('input',renderTables); $('#filter-category').addEventListener('change',renderTables); $('#filter-supplier').addEventListener('change',renderTables);
$('#inventory-body').addEventListener('click',e=>{const edit=e.target.closest('[data-edit]');const del=e.target.closest('[data-delete]');if(edit)openModal(allProducts.find(p=>p.id===edit.dataset.edit));if(del)deleteItem(del.dataset.delete);});
$('#refresh-graph').addEventListener('click',loadGraph);
$('#seed-button').addEventListener('click',async()=>{const btn=$('#seed-button');btn.disabled=true;btn.textContent='Loading…';try{const result=await api('/api/seed',{method:'POST'});await loadProducts();await loadHealth();toast(`${result.inserted} sample product(s) added. Graph prepared.`);if(!$('#relationships-section').classList.contains('hidden'))loadGraph();}catch(e){toast(e.message,true);}finally{btn.disabled=false;btn.textContent='↻ Load sample data';}});
$('#item-modal').addEventListener('click',e=>{if(e.target===$('#item-modal'))closeModal();});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});
(async function init(){await loadHealth();await loadCategories();try{await loadProducts();}catch(e){toast('Cannot reach MongoDB. Start MongoDB and refresh.',true);}await loadHealth();})();
