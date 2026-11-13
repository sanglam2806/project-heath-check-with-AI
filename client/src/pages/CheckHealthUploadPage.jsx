import { useCallback, useEffect, useRef, useState } from 'react'
import { Upload, FileSpreadsheet, Search, Sparkles, Loader2, CheckCircle2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  uploadZip,
  scanProject,
  evaluateProject,
  previewExcelFile,
  parseExcelFileMapped,
  saveScanRun,
  getProjectSnapshots,
  createProject,
  getScanProgress,
  reEvaluateTicket,
  recomputeSummary,
} from '../api'
import { useEvaluationContext } from '../context/EvaluationContext'
import { useReEvalJob } from '../context/ReEvalJobContext'
import EvaluationResultsView from '../components/EvaluationResultsView'
import ExcelMappingModal from '../components/ExcelMappingModal'
import TrendHistoryPanel from '../components/TrendHistoryPanel'
import ScanProgressBar from '../components/ScanProgressBar'

const TICKET_TEMPLATE = `ticket_id\tsummary\tstatus\tdescription
PROJ-101\tImplement user login\tDone\tAdd POST /auth/login endpoint with JWT token
PROJ-102\tAdd password reset flow\tIn Progress\tEmail reset link and token expiry
PROJ-103\tBuild dashboard charts\tTo Do\tShow weekly activity bar chart`

function parseTickets(text) {
  const lines = text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)

  if (lines.length === 0) return []

  const header = lines[0].toLowerCase().split('\t').map((h) => h.trim())
  const idx = {
    id: header.indexOf('ticket_id'),
    summary: header.indexOf('summary'),
    status: header.indexOf('status'),
    desc: header.indexOf('description'),
    dueDate: header.indexOf('due_date'),
    issueType: header.indexOf('issue_type'),
    assignee: header.indexOf('assignee'),
  }

  // If no header matched, treat first line as data with defaults
  const hasHeader = idx.id !== -1 || idx.summary !== -1
  const dataLines = hasHeader ? lines.slice(1) : lines

  return dataLines
    .map((line) => {
      const cols = line.split('\t')
      const get = (i) => (i >= 0 ? (cols[i] || '').trim() : '')
      const ticket = {
        ticket_id: get(idx.id) || get(0) || `TICKET-${Math.random().toString(36).slice(2, 7)}`,
        summary: get(idx.summary) || get(1) || '(untitled)',
        status: get(idx.status) || get(2) || 'To Do',
        description: get(idx.desc) || get(3) || '',
        due_date: get(idx.dueDate),
        issue_type: get(idx.issueType),
        assignee: get(idx.assignee),
      }
      return ticket
    })
    .filter((t) => t.ticket_id)
}

/**
 * "Upload ZIP/Excel" — the other half of the former Check Health Project
 * page: upload a ZIP source archive and Excel/TSV tickets, then run a
 * fresh check. No Git/Jira connect UI and no "Existing Project" re-run mode
 * here — every run here is a brand-new check, auto-creating its project
 * (named after the ZIP's filename) when it saves.
 */
export default function CheckHealthUploadPage() {
  const { t } = useTranslation()
  const { evaluation, setEvaluation } = useEvaluationContext()
  const { startJob, finishJob } = useReEvalJob()

  const [zipFile, setZipFile] = useState(null)
  const [ticketsText, setTicketsText] = useState(TICKET_TEMPLATE)
  const [excelFile, setExcelFile] = useState(null)
  const [excelParsing, setExcelParsing] = useState(false)
  const [excelInfo, setExcelInfo] = useState('')
  const [excelPreview, setExcelPreview] = useState(null) // { headers, preview_rows, suggested_mapping }
  // Set once the user confirms a column mapping for an uploaded Excel file --
  // carried through to saveScanRun so the project's real ticket source
  // (excel vs manual paste) gets recorded, instead of always leaving it
  // unknown (see project_ticket_connections).
  const [confirmedExcelSource, setConfirmedExcelSource] = useState(null) // { filename, mapping } | null
  const excelInputRef = useRef(null)
  const [fileName, setFileName] = useState('')
  // Restore 'done' immediately if a prior evaluation is already in context
  // (e.g. the user navigated to another sidebar page and back) so results
  // keep showing instead of resetting to a blank form.
  const [phase, setPhase] = useState(() => (evaluation?.summary ? 'done' : 'idle')) // idle | uploading | scanning | evaluating | done | error
  const [error, setError] = useState('')
  const fileInputRef = useRef(null)

  // Which project (if any) this run's result got saved under — set once
  // createProjectAndPersist creates/finds it — so the Trend History panel
  // above the results knows whose snapshots to show.
  const [resultProjectId, setResultProjectId] = useState(null)
  const [resultProjectName, setResultProjectName] = useState('')
  const [trendSnapshots, setTrendSnapshots] = useState([])
  // Feedback for the background POST /api/scan-runs save (best-effort — a
  // failure here never blocks the already-computed results from showing).
  const [dbSaveStatus, setDbSaveStatus] = useState({ status: 'idle', message: '' }) // idle | saving | saved | error
  // Layer 4 opt-in: agentic deep-dive (tool-calling LLM against the
  // already-extracted ZIP) for whatever the fast pipeline leaves
  // Incomplete/low-confidence. Off by default — slower/costlier than
  // Layers 1-2.
  const [enableDeepDive, setEnableDeepDive] = useState(false)
  // Polled from GET /api/scan-progress/{job_id} while a scan/evaluate call
  // is in flight -- see ScanProgressBar. Cleared whenever we're not loading.
  const [scanProgress, setScanProgress] = useState(null)
  const progressPollRef = useRef(null)
  // Which ticket (if any) is currently being re-evaluated individually via
  // the Ticket Evaluation Results table's per-row re-scan button.
  const [reEvaluatingTicketId, setReEvaluatingTicketId] = useState(null)

  useEffect(() => {
    if (!resultProjectId) {
      setTrendSnapshots([])
      return
    }
    let cancelled = false
    getProjectSnapshots(resultProjectId)
      .then((data) => {
        if (!cancelled) setTrendSnapshots(data)
      })
      .catch(() => {
        if (!cancelled) setTrendSnapshots([])
      })
    return () => {
      cancelled = true
    }
  }, [resultProjectId, dbSaveStatus.status])

  const tickets = evaluation?.tickets || []
  const results = evaluation?.results || []
  const summary = evaluation?.summary || null
  const health = evaluation?.health || null
  const trend = evaluation?.trend || null

  const handleFileChange = (e) => {
    const file = e.target.files?.[0]
    if (file) {
      setZipFile(file)
      setFileName(file.name)
      setError('')
    }
  }

  const handleExcelChange = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError('')
    setExcelParsing(true)
    try {
      const preview = await previewExcelFile(file)
      setExcelFile(file)
      setExcelPreview(preview)
    } catch (err) {
      setError(err.message || t('checkHealthUpload.failedToPreviewExcel'))
    } finally {
      setExcelParsing(false)
      if (excelInputRef.current) excelInputRef.current.value = ''
    }
  }

  const handleMappingConfirm = async (mapping, headerRow) => {
    if (!excelFile) return
    setExcelParsing(true)
    try {
      const data = await parseExcelFileMapped(excelFile, mapping, headerRow)
      setTicketsText(data.tsv)
      setExcelInfo(t('checkHealthUpload.loadedTickets', { count: data.ticket_count, filename: excelFile.name }))
      setConfirmedExcelSource({ filename: excelFile.name, mapping })
      setExcelPreview(null)
    } catch (err) {
      setError(err.message || t('checkHealthUpload.failedToParseExcel'))
    } finally {
      setExcelParsing(false)
    }
  }

  const handleMappingCancel = () => {
    setExcelPreview(null)
    setExcelFile(null)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    const file = e.dataTransfer.files?.[0]
    if (file) {
      setZipFile(file)
      setFileName(file.name)
      setError('')
    }
  }

  // No project to attach this run to yet — auto-create one named after the
  // uploaded ZIP's filename, then save the run under it.
  const createProjectAndPersist = useCallback(
    async ({ name, uploadId, tickets, results, summary, healthStatus, excelSource }) => {
      setDbSaveStatus({ status: 'saving', message: '' })
      try {
        const project = await createProject(name)
        setResultProjectId(project.id)
        setResultProjectName(project.name)
        await saveScanRun({
          project_id: project.id,
          run_type: 'new_check',
          scope: 'all',
          scope_note: null,
          upload_id: uploadId || null,
          is_snapshot: true,
          tickets,
          results,
          summary,
          health_status: healthStatus || 'OK',
          source_type: excelSource ? 'excel' : 'manual',
          excel_filename: excelSource?.filename || null,
          excel_mapping: excelSource?.mapping || null,
        })
        setDbSaveStatus({
          status: 'saved',
          message: project.created
            ? t('checkHealthConnect.createdProjectAndSaved', { name: project.name })
            : t('checkHealthConnect.savedToExistingProject', { name: project.name }),
        })
      } catch (err) {
        setDbSaveStatus({ status: 'error', message: err.message || t('checkHealthConnect.failedToCreateProject') })
      }
    },
    [t]
  )

  // Ticket Evaluation Results table's per-row re-scan button: re-runs AI
  // for just this one ticket against the already-uploaded ZIP, and patches
  // only its row in place -- no full re-scan of the whole project.
  const handleReEvaluateTicket = useCallback(
    async (ticket) => {
      if (!evaluation?.uploadId) return
      setReEvaluatingTicketId(ticket.ticket_id)
      // Tracked globally (see ReEvalJobContext/ReEvalJobBanner) so the
      // in-progress/outcome feedback survives navigating to a different
      // page mid-request -- the request itself keeps running regardless.
      startJob({ ticketId: ticket.ticket_id, projectId: resultProjectId, projectName: resultProjectName })
      try {
        // Only ask the backend to persist this into the DB when the current
        // results are actually what's saved as the project's latest
        // snapshot -- otherwise we'd silently patch an older, unrelated
        // snapshot while this page still shows a newer unsaved scan.
        const canPersist = dbSaveStatus.status === 'saved' && !!resultProjectId
        const newResult = await reEvaluateTicket({
          ticket,
          uploadId: evaluation.uploadId,
          enableDeepDive,
          projectId: canPersist ? resultProjectId : undefined,
        })
        const newResults = evaluation.results.map((r) => (r.ticket_id === newResult.ticket_id ? newResult : r))
        let { summary: newSummary, health: newHealth, trend: newTrend } = evaluation
        try {
          const recomputed = await recomputeSummary({
            tickets: evaluation.tickets,
            results: newResults,
            scannedFiles: evaluation.summary?.scanned_files,
          })
          newSummary = recomputed.summary
          newHealth = recomputed.health
          newTrend = recomputed.trend
        } catch {
          // best-effort -- keep the last-known totals if recompute fails
        }
        setEvaluation({ ...evaluation, results: newResults, summary: newSummary, health: newHealth, trend: newTrend })
        finishJob({ status: 'done', assessment: newResult.assessment })
      } catch (err) {
        const message = err.message || t('evaluationResults.reEvaluateTicketFailed')
        setError(message)
        finishJob({ status: 'error', message })
      } finally {
        setReEvaluatingTicketId(null)
      }
    },
    [evaluation, enableDeepDive, dbSaveStatus, resultProjectId, resultProjectName, startJob, finishJob, setEvaluation, t]
  )

  const runPipeline = useCallback(async () => {
    if (!zipFile) {
      setError(t('checkHealthUpload.selectZipFirst'))
      return
    }
    const tickets = parseTickets(ticketsText)
    if (tickets.length === 0) {
      setError(t('checkHealthUpload.noValidTickets'))
      return
    }

    setError('')
    setDbSaveStatus({ status: 'idle', message: '' })
    setScanProgress(null)

    const jobId = crypto.randomUUID()
    progressPollRef.current = setInterval(() => {
      getScanProgress(jobId)
        .then((p) => {
          if (p && p.total > 0) setScanProgress(p)
        })
        .catch(() => {})
    }, 1500)

    try {
      // Step 1: Upload
      setPhase('uploading')
      const uploadRes = await uploadZip(zipFile)

      // Step 2: Scan
      setPhase('scanning')
      await scanProject(uploadRes.upload_id, tickets)

      // Step 3: Evaluate
      setPhase('evaluating')
      const evalRes = await evaluateProject(uploadRes.upload_id, tickets, enableDeepDive, jobId)
      setPhase('done')

      setEvaluation({
        uploadId: uploadRes.upload_id,
        tickets,
        results: evalRes.results || [],
        summary: evalRes.summary || null,
        health: evalRes.health || null,
        trend: evalRes.trend || null,
      })

      createProjectAndPersist({
        name: zipFile.name.replace(/\.zip$/i, ''),
        uploadId: uploadRes.upload_id,
        tickets,
        results: evalRes.results || [],
        summary: evalRes.summary || null,
        healthStatus: evalRes.health?.status,
        excelSource: confirmedExcelSource,
      })
    } catch (err) {
      setPhase('error')
      setError(err.message || t('checkHealthUpload.unexpectedError'))
    } finally {
      clearInterval(progressPollRef.current)
      progressPollRef.current = null
      setScanProgress(null)
    }
  }, [zipFile, ticketsText, enableDeepDive, setEvaluation, createProjectAndPersist, confirmedExcelSource, t])

  useEffect(() => {
    return () => {
      if (progressPollRef.current) clearInterval(progressPollRef.current)
    }
  }, [])

  const resetAll = () => {
    setZipFile(null)
    setFileName('')
    setPhase('idle')
    setError('')
    setDbSaveStatus({ status: 'idle', message: '' })
    setEvaluation(null)
    setResultProjectId(null)
    setResultProjectName('')
    setConfirmedExcelSource(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const isLoading = ['uploading', 'scanning', 'evaluating'].includes(phase)

  return (
    <>
      {/* Input Section */}
      <section className="card p-6">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left: Project Source */}
          <div>
            <h2 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
              <Upload size={16} className="text-primary-600" /> {t('checkHealthUpload.projectSource')}
            </h2>

            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
                zipFile
                  ? 'border-emerald-400 bg-emerald-50'
                  : 'border-slate-300 hover:border-primary-400 hover:bg-primary-50'
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".zip"
                className="hidden"
                onChange={handleFileChange}
              />
              {zipFile ? (
                <>
                  <FileSpreadsheet size={32} className="mx-auto text-emerald-500 mb-2" />
                  <p className="font-medium text-slate-800">{fileName}</p>
                  <p className="text-xs text-slate-500 mt-1">
                    {t('checkHealthUpload.dropZoneActive')}
                  </p>
                </>
              ) : (
                <>
                  <Upload size={32} className="mx-auto text-slate-400 mb-2" />
                  <p className="font-medium text-slate-600">
                    {t('checkHealthUpload.dropZoneIdle')}
                  </p>
                  <p className="text-xs text-slate-400 mt-1">{t('checkHealthUpload.orClickToBrowse')}</p>
                </>
              )}
            </div>
          </div>

          {/* Right: Tickets Source */}
          <div>
            <h2 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
              <Sparkles size={16} className="text-primary-600" /> {t('checkHealthUpload.ticketsSource')}
            </h2>

            {/* Excel upload */}
            <div className="mb-3 flex items-center gap-2">
              <input
                ref={excelInputRef}
                type="file"
                accept=".xlsx,.xlsm"
                className="hidden"
                onChange={handleExcelChange}
              />
              <button
                type="button"
                onClick={() => excelInputRef.current?.click()}
                disabled={excelParsing}
                className="px-3 py-1.5 text-xs font-medium rounded-lg border border-primary-200 text-primary-700 bg-primary-50 hover:bg-primary-100 cursor-pointer disabled:opacity-50"
              >
                {excelParsing ? (
                  <>
                    <Loader2 size={12} className="animate-spin inline mr-1" />
                    {t('checkHealthUpload.parsing')}
                  </>
                ) : (
                  <>
                    <FileSpreadsheet size={12} className="inline mr-1" />
                    {excelFile ? excelFile.name : t('checkHealthUpload.importFromExcel')}
                  </>
                )}
              </button>
              {excelInfo && (
                <span className="text-xs text-emerald-600">{excelInfo}</span>
              )}
            </div>

            <textarea
              value={ticketsText}
              onChange={(e) => setTicketsText(e.target.value)}
              rows={8}
              spellCheck={false}
              className="input-field font-mono text-xs leading-relaxed resize-y"
              placeholder="ticket_id&#9;summary&#9;status&#9;description"
            />
            <p className="text-xs text-slate-400 mt-1.5">
              {t('checkHealthUpload.tsvHintPrefix')} <strong>{t('checkHealthUpload.tsvHintImport')}</strong>{' '}
              {t('checkHealthUpload.tsvHintSuffix')}
              <br />
              {t('checkHealthUpload.tsvHintColumns')}{' '}
              <code className="bg-slate-100 px-1 rounded">ticket_id</code>,{' '}
              <code className="bg-slate-100 px-1 rounded">summary</code>,{' '}
              <code className="bg-slate-100 px-1 rounded">status</code>,{' '}
              <code className="bg-slate-100 px-1 rounded">description</code>.
              <br />
              {t('checkHealthUpload.tsvHintOptional')}{' '}
              <code className="bg-slate-100 px-1 rounded">due_date</code>,{' '}
              <code className="bg-slate-100 px-1 rounded">issue_type</code>,{' '}
              <code className="bg-slate-100 px-1 rounded">assignee</code>.
            </p>
          </div>
        </div>

        {/* Action buttons */}
        <div className="mt-6 flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-3">
            <button onClick={runPipeline} disabled={isLoading} className="btn-primary">
              {isLoading ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  {phase === 'uploading'
                    ? t('checkHealthUpload.uploading')
                    : phase === 'scanning'
                      ? t('checkHealthUpload.scanningCode')
                      : enableDeepDive
                        ? t('checkHealthUpload.evaluatingWithAiDeepDive')
                        : t('checkHealthUpload.evaluatingWithAi')}
                </>
              ) : (
                <>
                  <Search size={16} />
                  {t('checkHealthUpload.scanAndEvaluate')}
                </>
              )}
            </button>
            {phase !== 'idle' && (
              <button onClick={resetAll} className="btn-secondary">
                {t('checkHealthUpload.reset')}
              </button>
            )}
          </div>
          <label
            className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer"
            title={t('checkHealthConnect.deepDiveHelp')}
          >
            <input type="checkbox" checked={enableDeepDive} onChange={(e) => setEnableDeepDive(e.target.checked)} />
            {t('checkHealthConnect.deepDiveLabel')}
          </label>
          {phase === 'done' && dbSaveStatus.status !== 'idle' && (
            <span
              className={`inline-flex items-center gap-1.5 text-xs ${
                dbSaveStatus.status === 'error'
                  ? 'text-red-600'
                  : dbSaveStatus.status === 'saving'
                    ? 'text-slate-400'
                    : 'text-emerald-600'
              }`}
            >
              {dbSaveStatus.status === 'saving' && <Loader2 size={12} className="animate-spin" />}
              {dbSaveStatus.status === 'saved' && <CheckCircle2 size={12} />}
              {dbSaveStatus.status === 'saving' ? t('checkHealthUpload.savingToDb') : dbSaveStatus.message}
            </span>
          )}
        </div>

        {error && (
          <div className="mt-4 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
            {error}
          </div>
        )}
      </section>

      {/* Loading indicator */}
      {isLoading && (
        <div className="card p-8 flex flex-col items-center justify-center gap-3">
          <Loader2 size={36} className="animate-spin text-primary-600" />
          <p className="text-sm text-slate-600">
            {phase === 'uploading'
              ? t('checkHealthUpload.uploadingArchive')
              : phase === 'scanning'
                ? t('checkHealthUpload.scanningSource')
                : t('checkHealthUpload.runningAiEvaluation')}
          </p>
          {scanProgress ? (
            <ScanProgressBar progress={scanProgress} />
          ) : (
            <p className="text-xs text-slate-400">
              {t('checkHealthUpload.mayTakeAMinute')}
            </p>
          )}
        </div>
      )}

      {/* Results */}
      {phase === 'done' && summary && (
        <>
          {resultProjectId && (
            <TrendHistoryPanel projectName={resultProjectName} snapshots={trendSnapshots} />
          )}
          <EvaluationResultsView
            projectName={resultProjectName}
            tickets={tickets}
            results={results}
            summary={summary}
            health={health}
            trend={trend}
            onReEvaluateTicket={handleReEvaluateTicket}
            reEvaluatingTicketId={reEvaluatingTicketId}
          />
        </>
      )}

      {/* Excel column mapping modal */}
      {excelPreview && (
        <ExcelMappingModal
          open={!!excelPreview}
          headerRow={excelPreview.header_row}
          previewRows={excelPreview.preview_rows}
          suggestedMapping={excelPreview.suggested_mapping}
          onConfirm={handleMappingConfirm}
          onCancel={handleMappingCancel}
        />
      )}
    </>
  )
}
