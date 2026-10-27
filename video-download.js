(() => {
  const el = id => document.getElementById(id);
  let current = null, timer = null, pending = false, lastJob = null;
  const active = state => ['analyzing', 'downloading', 'merging'].includes(state);
  function message(text, error = false) {
    el('videoDownloadStatus').textContent = text;
    el('videoDownloadStatus').className = 'status' + (error ? ' error' : '');
  }
  async function request(path, data) {
    const response = await fetch(path, data ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)} : {});
    const result = await response.json();
    if (!response.ok) { const error = Error(result.error || '请求失败'); error.status = response.status; throw error; }
    return result;
  }
  function render(job) {
    lastJob = job;
    const running = active(job.state);
    el('videoAnalyze').disabled = running || pending;
    el('videoUrl').disabled = running || pending;
    el('videoProxy').disabled = running || pending;
    el('videoDownloadStart').disabled = job.state !== 'ready' || pending;
    el('videoResolution').disabled = job.state !== 'ready' || pending;
    el('videoDetails').hidden = !job.resolutions;
    el('videoSave').hidden = job.state !== 'done';
    el('videoRemove').hidden = running || !job.id;
    el('videoDownloadProgress').hidden = !running;
    if (job.state === 'downloading' && job.progress) el('videoDownloadProgress').value = job.progress;
    else el('videoDownloadProgress').removeAttribute('value');
    message(job.message, job.state === 'error');
    if (job.title) {
      el('videoTitle').textContent = job.title;
      const minutes = job.duration ? Math.floor(job.duration / 60) + ' 分 ' + Math.round(job.duration % 60) + ' 秒' : '时长未知';
      el('videoMeta').textContent = job.platform + ' · ' + minutes;
    }
    if (job.resolutions && el('videoResolution').dataset.job !== job.id) {
      el('videoResolution').replaceChildren(...job.resolutions.map(item => {
        const option = document.createElement('option'); option.value = item.height; option.textContent = item.label; return option;
      }));
      el('videoResolution').dataset.job = job.id;
    }
    if (job.state === 'done') {
      el('videoSave').href = job.file_url;
      el('videoSave').download = job.filename;
      el('videoSave').textContent = `保存视频到电脑 ↓ · ${(job.size / 1024 ** 2).toFixed(1)} MB`;
    }
    if (running) timer = setTimeout(poll, 1500);
  }
  async function poll() {
    clearTimeout(timer);
    if (!current) return;
    try { render(await request('/api/video/job/' + current)); }
    catch (error) {
      if (error.status === 404) {
        current = null; lastJob = null;
        for (const id of ['videoDetails', 'videoSave', 'videoRemove', 'videoDownloadProgress']) el(id).hidden = true;
        for (const id of ['videoUrl', 'videoProxy', 'videoAnalyze']) el(id).disabled = false;
        el('videoAnalyze').textContent = '读取视频信息';
        return message('任务已过期或服务已重启，请重新读取视频信息。', true);
      }
      message('无法读取任务状态：' + error.message + '。可点击重试查询。', true);
      el('videoAnalyze').textContent = '重试查询任务';
      el('videoAnalyze').disabled = false;
    }
  }
  el('videoAnalyze').onclick = async () => {
    if (pending) return;
    if (lastJob && active(lastJob.state)) {
      el('videoAnalyze').textContent = '读取视频信息';
      return poll();
    }
    const url = el('videoUrl').value.trim();
    if (!url) return message('请先粘贴视频网址。', true);
    pending = true; el('videoAnalyze').disabled = true;
    el('videoDetails').hidden = true; el('videoSave').hidden = true;
    el('videoDownloadStart').disabled = true;
    message('正在提交解析任务…');
    try {
      // Clean up an old result before starting a new task in this panel.
      if (current) await request('/api/video/remove', {id: current});
      current = null; lastJob = null; clearTimeout(timer);
      const job = await request('/api/video/analyze', {url, proxy: el('videoProxy').value.trim()});
      current = job.id; pending = false; render(job);
    } catch (error) {
      message(error.message, true); el('videoAnalyze').disabled = false;
    } finally { pending = false; }
  };
  el('videoDownloadStart').onclick = async () => {
    if (!current || pending) return;
    // Prevent edits after parsing from silently downloading a different URL.
    pending = true; el('videoDownloadStart').disabled = true;
    try {
      const job = await request('/api/video/download', {id: current, height: Number(el('videoResolution').value)});
      pending = false; render(job);
    } catch (error) {
      pending = false; if (lastJob) render(lastJob); message(error.message, true);
    }
  };
  function invalidate() {
    el('videoDetails').hidden = true; el('videoSave').hidden = true;
    el('videoDownloadStart').disabled = true;
    message('网址或代理已修改，请重新读取视频信息。');
  }
  el('videoUrl').oninput = invalidate; el('videoProxy').oninput = invalidate;
  el('videoUrl').onkeydown = event => { if (event.key === 'Enter' && !el('videoAnalyze').disabled) el('videoAnalyze').click(); };
  el('videoRemove').onclick = async () => {
    if (!current || pending) return;
    try {
      await request('/api/video/remove', {id: current});
      current = null; lastJob = null; clearTimeout(timer);
      el('videoDetails').hidden = true; el('videoSave').hidden = true; el('videoRemove').hidden = true;
      message('任务和临时视频已清理。');
    } catch (error) { message(error.message, true); }
  };
  fetch('/api/status').then(response => response.json()).then(info => {
    if (!info.video_download) message('缺少下载组件，请运行安装脚本并重启工具。', true);
    else if (!info.js_runtime) message('缺少 YouTube 脚本运行组件，建议运行安装脚本后重启工具。', true);
  }).catch(() => message('无法连接本地服务，请通过启动脚本打开工具。', true));
})();
