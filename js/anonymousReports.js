document.addEventListener('DOMContentLoaded', () => {
  const reportDialog = document.getElementById('public-report-dialog');
  const reportForms = [...document.querySelectorAll('[data-anonymous-report-form]')];
  const reportsNavigation = document.getElementById('reports-navigation');
  const reportList = document.getElementById('anonymous-report-list');
  const reportStatus = document.getElementById('anonymous-reports-status');
  if (!reportForms.length) return;

  const STATUS_STEPS = [
    ['RECEIVED', 'Received'],
    ['UNDER_REVIEW', 'Under review'],
    ['INVESTIGATING', 'Investigating'],
    ['ACTION_TAKEN', 'Action taken'],
    ['CLOSED', 'Closed'],
  ];

  async function readJson(response) {
    const text = await response.text();
    try {
      return text ? JSON.parse(text) : {};
    } catch (error) {
      return {};
    }
  }

  function createProgress(statusInfo) {
    const wrapper = document.createElement('div');
    wrapper.className = 'report-progress';
    const step = Math.min(Math.max(statusInfo.status_step || 1, 1), STATUS_STEPS.length);
    const label = STATUS_STEPS[step - 1][1];
    const bar = document.createElement('div');
    bar.className = 'report-progress-bar';
    bar.setAttribute('role', 'progressbar');
    bar.setAttribute('aria-valuemin', '1');
    bar.setAttribute('aria-valuemax', String(STATUS_STEPS.length));
    bar.setAttribute('aria-valuenow', String(step));
    bar.setAttribute('aria-valuetext', label);
    const fill = document.createElement('div');
    fill.className = 'report-progress-fill';
    fill.dataset.status = statusInfo.status;
    fill.style.width = `${(step / STATUS_STEPS.length) * 100}%`;
    bar.appendChild(fill);
    const steps = document.createElement('ol');
    steps.className = 'report-progress-steps';
    STATUS_STEPS.forEach(([, text], index) => {
      const item = document.createElement('li');
      item.textContent = text;
      if (index + 1 < step) item.className = 'done';
      if (index + 1 === step) item.className = 'current';
      steps.appendChild(item);
    });
    const caption = document.createElement('p');
    caption.className = 'muted';
    caption.textContent = `Status: ${label}`
      + (statusInfo.status_updated_at ? ` · updated ${new Date(statusInfo.status_updated_at).toLocaleString()}` : '');
    wrapper.append(bar, steps, caption);
    return wrapper;
  }

  function addProgressLookup(form) {
    const section = document.createElement('div');
    section.className = 'report-progress-lookup';
    const label = document.createElement('label');
    label.textContent = 'Check the progress of a report';
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'Reference, e.g. AR-20261009-XXXXXXXXXX';
    input.autocomplete = 'off';
    input.maxLength = 40;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-secondary';
    button.textContent = 'Check progress';
    const result = document.createElement('div');
    result.setAttribute('role', 'status');
    result.setAttribute('aria-live', 'polite');
    const check = async (reference) => {
      const value = reference.trim();
      if (!value) {
        result.textContent = 'Enter the reference you received when submitting.';
        return;
      }
      button.disabled = true;
      result.textContent = 'Checking...';
      try {
        const response = await fetch(window.DifanApp.apiUrl(
          `/api/portal/anonymous-reports/status/${encodeURIComponent(value)}`,
        ));
        const data = await readJson(response);
        if (!response.ok) throw new Error(data.message || 'Unable to check this report right now.');
        result.replaceChildren(createProgress(data.report_status));
      } catch (error) {
        result.textContent = error.message || 'Unable to check this report right now.';
      } finally {
        button.disabled = false;
      }
    };
    button.addEventListener('click', () => check(input.value));
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        check(input.value);
      }
    });
    section.append(label, input, button, result);
    form.insertAdjacentElement('afterend', section);
    form.reportProgressCheck = (reference) => {
      input.value = reference;
      result.replaceChildren(createProgress({ status: 'RECEIVED', status_step: 1 }));
    };
  }

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

  async function bossRequest(path, options = {}) {
    const response = await fetch(window.DifanApp.apiUrl(path), {
      ...options,
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        Authorization: 'Bearer ' + getToken(),
      },
    });
    const data = await readJson(response);
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
      const activeRecorder = new MediaRecorder(recordingStream, options);
      recorder = activeRecorder;
      recordingForm = form;
      const chunks = [];
      activeRecorder.addEventListener('dataavailable', (event) => {
        if (event.data.size) chunks.push(event.data);
      });
      activeRecorder.addEventListener('stop', () => {
        const type = activeRecorder.mimeType || 'audio/webm';
        const voiceNote = new File(chunks, 'voice-note.webm', { type });
        if (voiceNote.size) {
          recordedVoice = voiceNote;
          activeRecordings.set(form, voiceNote);
          setRecordingStatus(form, 'Voice note recorded. It will be included with your report.');
        } else {
          setRecordingStatus(form, 'No audio was captured. Please try recording again.');
        }
        recordingStream?.getTracks().forEach((track) => track.stop());
        recordingStream = null;
        if (recorder === activeRecorder) recorder = null;
        if (recordingForm === form) recordingForm = null;
        button.textContent = 'Record another voice note';
        button.disabled = false;
      }, { once: true });
      activeRecorder.addEventListener('error', () => {
        recordingStream?.getTracks().forEach((track) => track.stop());
        recordingStream = null;
        if (recorder === activeRecorder) recorder = null;
        if (recordingForm === form) recordingForm = null;
        button.textContent = 'Record voice note';
        button.disabled = false;
        setRecordingStatus(form, 'Recording failed. Check microphone permission and try again.');
      }, { once: true });
      activeRecorder.start();
      button.textContent = 'Stop recording';
      button.disabled = false;
      setRecordingStatus(form, 'Recording voice note...');
    } catch (error) {
      setRecordingStatus(form, error.message || 'Unable to access the microphone.');
      recordingStream?.getTracks().forEach((track) => track.stop());
      recordingStream = null;
      recorder = null;
      recordingForm = null;
      button.textContent = 'Record voice note';
      button.disabled = false;
    }
  }

  for (const form of reportForms) {
    addProgressLookup(form);
    const recordButton = form.querySelector('[data-record-voice]');
    recordButton?.addEventListener('click', () => {
      if (recorder && recordingForm === form) {
        try {
          if (recorder.state !== 'inactive') recorder.stop();
          setRecordingStatus(form, 'Stopping recording...');
        } catch (error) {
          recordingStream?.getTracks().forEach((track) => track.stop());
          recordingStream = null;
          recorder = null;
          recordingForm = null;
          recordButton.textContent = 'Record voice note';
          setRecordingStatus(form, error.message || 'Unable to stop the recording. Please try again.');
        }
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

      reportDialog?.addEventListener('close', () => {
        if (recorder && recordingForm && recorder.state !== 'inactive') {
          try {
            recorder.stop();
          } catch (error) {
            recordingStream?.getTracks().forEach((track) => track.stop());
            recordingStream = null;
            recorder = null;
            recordingForm = null;
          }
        }
      });
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
        const response = await fetch(window.DifanApp.apiUrl('/api/portal/anonymous-reports'), {
          method: 'POST',
          body: payload,
        });
        const data = await readJson(response);
        if (!response.ok) throw new Error(data.message || 'Unable to submit the report.');
        form.reset();
        activeRecordings.delete(form);
        status.textContent = `${data.message} Reference: ${data.reference} — keep it to check progress later.`;
        form.reportProgressCheck?.(data.reference);
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
          window.DifanApp.apiUrl(`/api/portal/anonymous-reports/${report.id}/attachments/${encodeURIComponent(attachment.id)}`),
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
        const progress = document.createElement('div');
        const renderProgress = (info) => progress.replaceChildren(createProgress(info));
        renderProgress(report);
        const controls = document.createElement('div');
        controls.className = 'report-status-controls';
        const select = document.createElement('select');
        select.setAttribute('aria-label', `Status for report ${report.reference}`);
        STATUS_STEPS.forEach(([value, text]) => {
          const option = document.createElement('option');
          option.value = value;
          option.textContent = text;
          option.selected = value === report.status;
          select.appendChild(option);
        });
        const save = document.createElement('button');
        save.type = 'button';
        save.className = 'btn btn-secondary';
        save.textContent = 'Update status';
        save.addEventListener('click', async () => {
          save.disabled = true;
          try {
            const data = await bossRequest(`/api/portal/anonymous-reports/${report.id}/status`, {
              method: 'PATCH',
              body: JSON.stringify({ status: select.value }),
            });
            renderProgress(data.report);
            reportStatus.textContent = `Report ${report.reference} marked as ${select.selectedOptions[0].textContent}.`;
          } catch (error) {
            reportStatus.textContent = error.message || 'Unable to update the report status.';
          } finally {
            save.disabled = false;
          }
        });
        controls.append(select, save);
        article.append(heading, progress, controls, description, attachments);
        reportList.appendChild(article);
      }
    } catch (error) {
      reportStatus.textContent = error.message || 'Unable to load anonymous reports.';
    }
  }

  reportsNavigation?.addEventListener('click', loadBossReports);
  document.getElementById('refresh-anonymous-reports')?.addEventListener('click', loadBossReports);
});
