document.addEventListener('DOMContentLoaded', () => {
  const reportDialog = document.getElementById('public-report-dialog');
  const reportForms = [...document.querySelectorAll('[data-anonymous-report-form]')];
  const reportsNavigation = document.getElementById('reports-navigation');
  const reportList = document.getElementById('anonymous-report-list');
  const reportStatus = document.getElementById('anonymous-reports-status');
  if (!reportForms.length) return;

  const activeRecordings = new Map();
  let recordingStream = null;
  let recorder = null;
  let recordingForm = null;
  let recordedVoice = null;
  let objectUrls = [];

  function getToken() {
    const token = localStorage.getItem('jwt_token');
    if (!token) throw new Error('Please sign in as the Boss to view reports.');
    return token;
  }

  async function bossRequest(path) {
    const response = await fetch(`http://localhost:5000${path}`, {
      headers: { Authorization: 'Bearer ' + getToken() },
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || 'Unable to load reports.');
    return data;
  }

  document.querySelectorAll('[data-open-public-report]').forEach((button) => {
    button.addEventListener('click', () => reportDialog?.showModal());
  });
  document.querySelectorAll('[data-close-public-report]').forEach((button) => {
    button.addEventListener('click', () => reportDialog?.close());
  });

  function setRecordingStatus(form, message) {
    const status = form.querySelector('[data-recording-status]');
    if (status) status.textContent = message;
  }

  async function beginRecording(form, button) {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setRecordingStatus(form, 'Voice recording is not available in this browser.');
      return;
    }
    try {
      recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const options = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? { mimeType: 'audio/webm;codecs=opus' }
        : {};
      recorder = new MediaRecorder(recordingStream, options);
      recordingForm = form;
      const chunks = [];
      recorder.addEventListener('dataavailable', (event) => {
        if (event.data.size) chunks.push(event.data);
      });
      recorder.addEventListener('stop', () => {
        const type = recorder.mimeType || 'audio/webm';
        recordedVoice = new File(chunks, 'voice-note.webm', { type });
        activeRecordings.set(form, recordedVoice);
        setRecordingStatus(form, 'Voice note recorded. It will be included with your report.');
        recordingStream?.getTracks().forEach((track) => track.stop());
        recordingStream = null;
        recorder = null;
        recordingForm = null;
        button.textContent = 'Record another voice note';
        button.disabled = false;
      }, { once: true });
      recorder.start();
      button.textContent = 'Stop recording';
      setRecordingStatus(form, 'Recording voice note...');
    } catch (error) {
      setRecordingStatus(form, error.message || 'Unable to access the microphone.');
      recordingStream?.getTracks().forEach((track) => track.stop());
      recordingStream = null;
      button.disabled = false;
    }
  }

  for (const form of reportForms) {
    const recordButton = form.querySelector('[data-record-voice]');
    recordButton?.addEventListener('click', () => {
      if (recorder && recordingForm === form) {
        recordButton.disabled = true;
        recorder.stop();
      } else if (!recorder) {
        recordButton.disabled = true;
        beginRecording(form, recordButton);
      }
    });

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const submitButton = form.querySelector('button[type="submit"]');
      const status = form.querySelector('[data-report-status]');
      const fileInput = form.querySelector('input[type="file"]');
      const description = form.querySelector('textarea[name="description"]');
      const files = [...fileInput.files];
      const voiceFile = activeRecordings.get(form);
      if (voiceFile) files.push(voiceFile);
      if (!description.value.trim() && !files.length) {
        status.textContent = 'Add report details or attach an image, video, or voice note.';
        return;
      }
      if (files.length > 5 || files.some((file) => file.size > 15 * 1024 * 1024)) {
        status.textContent = 'Attach no more than 5 files, with each file 15 MB or smaller.';
        return;
      }

      submitButton.disabled = true;
      status.textContent = 'Submitting report anonymously...';
      const payload = new FormData();
      payload.append('description', description.value);
      for (const file of files) payload.append('attachments', file, file.name);
      try {
        const response = await fetch('http://localhost:5000/api/portal/anonymous-reports', {
          method: 'POST',
          body: payload,
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || 'Unable to submit the report.');
        form.reset();
        activeRecordings.delete(form);
        status.textContent = `${data.message} Reference: ${data.reference}`;
        setRecordingStatus(form, 'No voice note recorded.');
        if (form.closest('dialog')) reportDialog.close();
      } catch (error) {
        status.textContent = error.message || 'Unable to submit the report.';
      } finally {
        submitButton.disabled = false;
      }
    });
  }

  function addAttachment(container, report, attachment) {
    const link = document.createElement('a');
    link.className = 'boss-report-attachment';
    link.textContent = `${attachment.media_type} attachment · ${(attachment.size_bytes / (1024 * 1024)).toFixed(2)} MB`;
    link.href = '#';
    link.addEventListener('click', async (event) => {
      event.preventDefault();
      link.setAttribute('aria-busy', 'true');
      try {
        const response = await fetch(
          `http://localhost:5000/api/portal/anonymous-reports/${report.id}/attachments/${encodeURIComponent(attachment.id)}`,
          { headers: { Authorization: 'Bearer ' + getToken() } },
        );
        if (!response.ok) {
          const data = await response.json();
          throw new Error(data.message || 'Unable to open this attachment.');
        }
        const objectUrl = URL.createObjectURL(await response.blob());
        objectUrls.push(objectUrl);
        const preview = document.createElement(attachment.media_type === 'image'
          ? 'img'
          : attachment.media_type === 'video' ? 'video' : 'audio');
        preview.className = 'boss-report-media';
        preview.src = objectUrl;
        if (attachment.media_type !== 'image') {
          preview.controls = true;
          preview.preload = 'metadata';
        }
        link.replaceWith(preview);
      } catch (error) {
        reportStatus.textContent = error.message || 'Unable to open this attachment.';
        link.removeAttribute('aria-busy');
      }
    });
    container.appendChild(link);
  }

  async function loadBossReports() {
    if (!reportList || !reportStatus || window.DifanApp?.state?.currentUser?.role !== 'boss') return;
    reportStatus.textContent = 'Loading anonymous reports...';
    reportList.replaceChildren();
    objectUrls.forEach((url) => URL.revokeObjectURL(url));
    objectUrls = [];
    try {
      const data = await bossRequest('/api/portal/anonymous-reports');
      if (!data.reports.length) {
        reportStatus.textContent = 'No reports have been submitted.';
        return;
      }
      reportStatus.textContent = `${data.reports.length} report${data.reports.length === 1 ? '' : 's'} available to the Boss.`;
      for (const report of data.reports) {
        const article = document.createElement('article');
        article.className = 'workflow-record';
        const heading = document.createElement('h3');
        heading.textContent = `${report.reference} · ${new Date(report.created_at).toLocaleString()}`;
        const description = document.createElement('p');
        description.textContent = report.description || 'No written details; see the attached media.';
        const attachments = document.createElement('div');
        attachments.className = 'boss-report-attachments';
        for (const attachment of report.attachments) addAttachment(attachments, report, attachment);
        article.append(heading, description, attachments);
        reportList.appendChild(article);
      }
    } catch (error) {
      reportStatus.textContent = error.message || 'Unable to load anonymous reports.';
    }
  }

  reportsNavigation?.addEventListener('click', loadBossReports);
  document.getElementById('refresh-anonymous-reports')?.addEventListener('click', loadBossReports);
});
