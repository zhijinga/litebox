// Browser-only image processing and uncompressed ZIP packaging (no external libraries).
(() => {
  const el = id => document.getElementById(id);
  let items = [], processing = false;
  const bytes = value => value < 1024 * 1024 ? (value / 1024).toFixed(1) + ' KB' : (value / 1024 ** 2).toFixed(2) + ' MB';
  const status = text => { el('imageStatus').textContent = text; };
  function controls() {
    el('imageCompress').disabled = processing || !items.length;
    el('imageClear').disabled = processing || !items.length;
    for (const id of ['imageFiles', 'imageFormat', 'imageQuality', 'imageMax']) el(id).disabled = processing;
    el('imageZip').hidden = !items.some(item => item.output);
    el('imageZip').disabled = processing;
    el('imageQuality').disabled = processing || el('imageFormat').value === 'png';
    el('qualityValue').textContent = el('imageFormat').value === 'png' ? '（PNG 不使用质量参数）' : el('imageQuality').value + '%';
  }
  function release(item) {
    URL.revokeObjectURL(item.sourceUrl);
    if (item.outputUrl) URL.revokeObjectURL(item.outputUrl);
  }
  function render() {
    const list = el('imageList'); list.replaceChildren();
    items.forEach(item => {
      const row = document.createElement('div'); row.className = 'image-row';
      const thumb = document.createElement('img'); thumb.src = item.outputUrl || item.sourceUrl; thumb.alt = ''; thumb.loading = 'lazy';
      const info = document.createElement('div'); info.className = 'image-info';
      const name = document.createElement('span'); name.className = 'image-name'; name.textContent = item.file.name;
      const meta = document.createElement('span'); meta.className = 'image-meta';
      meta.textContent = bytes(item.file.size) + ' · ' + item.state;
      info.append(name, meta); row.append(thumb, info);
      if (item.output) {
        const link = document.createElement('a'); link.href = item.outputUrl; link.download = item.name; link.textContent = '下载'; row.append(link);
      }
      const remove = document.createElement('button'); remove.textContent = '移除'; remove.disabled = processing;
      remove.setAttribute('aria-label', '移除 ' + item.file.name);
      remove.onclick = () => { release(item); items = items.filter(other => other !== item); render(); controls(); };
      row.append(remove); list.append(row);
    });
    controls();
  }
  function add(files) {
    if (processing) return;
    let added = 0, rejected = 0;
    for (const file of files) {
      if (items.length >= 100 || !/\.(jpe?g|png|webp)$/i.test(file.name) || !file.size || file.size > 30 * 1024 ** 2) { rejected++; continue; }
      items.push({ file, sourceUrl: URL.createObjectURL(file), state: '待压缩' }); added++;
    }
    render(); status(`已追加 ${added} 张，共 ${items.length} 张。` + (rejected ? ` 已跳过 ${rejected} 个文件（格式、大小或数量超限）。` : ''));
  }
  function invalidate() {
    for (const item of items) {
      if (item.outputUrl) URL.revokeObjectURL(item.outputUrl);
      item.output = null; item.outputUrl = null; item.state = '设置已更新，待重新压缩';
    }
    el('imageProgress').hidden = true; render(); status('设置已更新，点击开始批量压缩。');
  }
  el('imageFiles').onchange = e => { add(e.target.files); e.target.value = ''; };
  for (const type of ['dragenter', 'dragover']) el('imageDrop').addEventListener(type, e => { e.preventDefault(); if (!processing) el('imageDrop').classList.add('over'); });
  for (const type of ['dragleave', 'drop']) el('imageDrop').addEventListener(type, e => { e.preventDefault(); el('imageDrop').classList.remove('over'); });
  el('imageDrop').addEventListener('drop', e => add(e.dataTransfer.files));
  for (const id of ['imageFormat', 'imageQuality', 'imageMax']) el(id).onchange = invalidate;
  el('imageQuality').oninput = () => { el('qualityValue').textContent = el('imageQuality').value + '%'; };
  el('imageClear').onclick = () => { items.forEach(release); items = []; el('imageProgress').hidden = true; render(); status('已清空，可重新选择图片。'); };
  async function compress(item, format, quality, maxSide) {
    // Read dimensions before allocating a canvas to avoid excessive canvas memory.
    const image = new Image(); image.src = item.sourceUrl;
    await image.decode();
    const w = image.naturalWidth, h = image.naturalHeight;
    if (!w || !h || w * h > 40_000_000) throw Error('图片超过 4000 万像素或尺寸无效');
    const scale = maxSide ? Math.min(1, maxSide / Math.max(w, h)) : 1;
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(w * scale)); canvas.height = Math.max(1, Math.round(h * scale));
    try {
      const ctx = canvas.getContext('2d');
      if (!ctx) throw Error('浏览器无法创建图片画布');
      if (format === 'jpeg') { ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height); }
      ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((resolve, reject) => canvas.toBlob(value => value ? resolve(value) : reject(Error('编码失败')), 'image/' + format, quality));
      if (blob.type !== 'image/' + format) throw Error('当前浏览器不支持此输出格式，请换成 JPG 或 PNG');
      const ext = format === 'jpeg' ? 'jpg' : format;
      item.name = item.file.name.replace(/\.[^.]+$/, '') + '_压缩.' + ext;
      item.output = blob; item.outputUrl = URL.createObjectURL(blob);
      const percent = (1 - blob.size / item.file.size) * 100;
      item.state = `${bytes(blob.size)} · ${canvas.width} × ${canvas.height} · ` + (percent >= 0 ? `减小 ${percent.toFixed(1)}%` : `增大 ${(-percent).toFixed(1)}%，可降低质量或尺寸`);
    } finally { canvas.width = canvas.height = 1; }
  }
  el('imageCompress').onclick = async () => {
    if (processing || !items.length) return;
    invalidate(); processing = true;
    const format = el('imageFormat').value, quality = Number(el('imageQuality').value) / 100, maxSide = Number(el('imageMax').value);
    el('imageProgress').hidden = false; el('imageProgress').max = items.length; el('imageProgress').value = 0;
    render(); let failed = 0;
    try {
      for (let i = 0; i < items.length; i++) {
        status(`正在压缩 ${i + 1} / ${items.length}：${items[i].file.name}`);
        items[i].state = '正在压缩…';
        try { await compress(items[i], format, quality, maxSide); }
        catch (error) { failed++; items[i].state = '失败：' + (error.message || '图片无法解码'); }
        el('imageProgress').value = i + 1; render();
      }
      const done = items.filter(item => item.output);
      const before = done.reduce((sum, item) => sum + item.file.size, 0), after = done.reduce((sum, item) => sum + item.output.size, 0);
      status(`完成 ${done.length} 张${failed ? `，失败 ${failed} 张` : ''}。成功文件：${bytes(before)} → ${bytes(after)}。可逐张下载或打包下载。`);
    } finally { processing = false; render(); }
  };

  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; table[n] = c >>> 0; }
  function crc32(data) { let crc = 0xffffffff; for (const byte of data) crc = table[(crc ^ byte) & 255] ^ (crc >>> 8); return (crc ^ 0xffffffff) >>> 0; }
  // ZIP STORE: compressed images rarely benefit from another compression pass.
  async function zipImages(entries) {
    const parts = [], directory = []; let offset = 0, centralSize = 0;
    const encoder = new TextEncoder();
    for (let i = 0; i < entries.length; i++) {
      const item = entries[i], data = new Uint8Array(await item.output.arrayBuffer());
      // Index prefix keeps duplicate basenames distinct on case-insensitive filesystems.
      const name = encoder.encode(String(i + 1).padStart(3, '0') + '_' + item.name.replace(/[\\/\x00-\x1f]/g, '_'));
      const crc = crc32(data), header = new Uint8Array(30), h = new DataView(header.buffer);
      h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint16(6, 0x800, true); h.setUint16(12, 0x21, true);
      h.setUint32(14, crc, true); h.setUint32(18, data.length, true); h.setUint32(22, data.length, true); h.setUint16(26, name.length, true);
      parts.push(header, name, item.output);
      const central = new Uint8Array(46), c = new DataView(central.buffer);
      c.setUint32(0, 0x02014b50, true); c.setUint16(4, 20, true); c.setUint16(6, 20, true); c.setUint16(8, 0x800, true); c.setUint16(14, 0x21, true);
      c.setUint32(16, crc, true); c.setUint32(20, data.length, true); c.setUint32(24, data.length, true); c.setUint16(28, name.length, true); c.setUint32(42, offset, true);
      directory.push(central, name); offset += header.length + name.length + data.length; centralSize += central.length + name.length;
      if (offset + centralSize > 0xffffffff) throw Error('打包超过 4 GB，请分批下载');
    }
    const end = new Uint8Array(22), e = new DataView(end.buffer);
    e.setUint32(0, 0x06054b50, true); e.setUint16(8, entries.length, true); e.setUint16(10, entries.length, true); e.setUint32(12, centralSize, true); e.setUint32(16, offset, true);
    return new Blob([...parts, ...directory, end], { type: 'application/zip' });
  }
  el('imageZip').onclick = async () => {
    if (processing) return;
    const entries = items.filter(item => item.output); if (!entries.length) return;
    processing = true; render(); status('正在打包，请稍候…');
    try {
      const blob = await zipImages(entries), url = URL.createObjectURL(blob);
      const link = document.createElement('a'); link.href = url; link.download = '声屿_压缩图片.zip'; document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000); status(`已生成 ZIP，包含 ${entries.length} 张图片。`);
    } catch (error) { status('打包失败：' + error.message); }
    finally { processing = false; render(); }
  };
  controls();
})();
