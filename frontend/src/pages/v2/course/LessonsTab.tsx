import { useCallback, useEffect, useState } from 'react';
import { studyApi, type LessonRow } from '../../../api/v2';
import JobCard from '../../../components/v2/JobCard';
import LessonPlayer from '../../../components/v2/LessonPlayer';
import { useCourse } from '../courseContext';
import st from '../v2.module.css';
import s from '../../../design/shared.module.css';

type TopicRow = { topic_id: string; name: string; module: number; lesson: LessonRow | null };

export default function LessonsTab() {
  const { course, snapshot } = useCourse();
  const [topics, setTopics] = useState<TopicRow[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [job, setJob] = useState<string | null>(null);

  const load = useCallback(() => studyApi.lessons(course.code).then(setTopics).catch(() => setTopics([])), [course.code]);
  useEffect(() => {
    load();
  }, [load]);

  if (!topics) return <span className="spinner" />;
  const prob = new Map((snapshot?.topics ?? []).map((t) => [t.topic_id, t.probability_next]));
  const current = topics.find((t) => t.topic_id === selected) ?? null;
  const lesson = current?.lesson ?? null;

  const make = async (topicId: string) => {
    const r = await studyApi.createLesson(course.code, topicId);
    setSelected(topicId);
    setJob(r.job_id);
  };
  const exportVideo = async () => {
    if (!lesson) return;
    const r = await studyApi.renderVideo(lesson.id);
    setJob(r.job_id);
  };

  return (
    <div className={st.lessonsLayout}>
      <aside className={st.topicList}>
        {course.modules.map((m) => (
          <div key={m.no} className={st.stack}>
            <div className="caps">Module {m.no} · {m.title}</div>
            {topics.filter((t) => t.module === m.no).map((t) => (
              <button key={t.topic_id} className={t.topic_id === selected ? st.paperItemActive : st.paperItem} onClick={() => setSelected(t.topic_id)}>
                <span className={st.topicName}>{t.name}</span>
                <span className={st.topicState}>
                  {t.lesson?.status === 'ready' ? (t.lesson.has_video ? '▶ video' : '▶') : t.lesson?.status === 'queued' ? '…' : ''}
                  {prob.has(t.topic_id) && <span className={st.muted}> {Math.round((prob.get(t.topic_id) ?? 0) * 100)}%</span>}
                </span>
              </button>
            ))}
          </div>
        ))}
      </aside>

      <section className={st.stack}>
        {job && <JobCard key={job} jobId={job} compact onDone={() => { load(); }} />}
        {!current && (
          <div className={`card ${st.empty}`}>
            <h2 className={st.emptyTitle}>Narrated lessons</h2>
            <p>Pick a topic. A lesson is written from that topic's real past questions, the syllabus line and your notes, then plays as animated
              slides with a voice-over — and can be exported as an MP4, rendered entirely on this computer.</p>
          </div>
        )}
        {current && !lesson && (
          <div className={`card ${st.empty}`}>
            <h2 className={st.emptyTitle}>{current.name}</h2>
            <p>No lesson yet. Writing one takes about a minute (one short agy call).</p>
            <button className={s.btnPrimary} style={{ marginTop: 16 }} onClick={() => make(current.topic_id)}>Make lesson</button>
          </div>
        )}
        {current && lesson?.status === 'queued' && <div className={`card ${st.empty}`}><span className="spinner" /><p>Writing the lesson…</p></div>}
        {current && lesson?.status === 'failed' && (
          <div className={`card ${st.cardPad}`}>
            <p className={st.flagNote}>The lesson could not be written: {lesson.error}</p>
            <button className={s.btnGhost} onClick={() => make(current.topic_id)}>Try again</button>
          </div>
        )}
        {current && lesson?.status === 'ready' && lesson.deck && (
          <>
            <div className={st.row}>
              <h2 className={st.sectionTitle}>{lesson.deck.title}</h2>
              <span className={st.spacer} />
              <button className={s.btnGhost} onClick={() => make(current.topic_id)}>Rewrite</button>
              <button className={s.btnPrimary} onClick={exportVideo} disabled={lesson.video_status === 'rendering'}>
                {lesson.has_video ? 'Re-render MP4' : lesson.video_status === 'rendering' ? 'Rendering…' : 'Export MP4'}
              </button>
            </div>
            <LessonPlayer key={lesson.id} deck={lesson.deck} courseCode={course.code} />
            {lesson.has_video && (
              <div className={`card ${st.cardPad} ${st.stack}`}>
                <div className="caps">Exported video · local narration</div>
                <video className={st.video} controls src={studyApi.videoUrl(lesson.id)} />
                <a href={studyApi.videoUrl(lesson.id)} download>Download MP4</a>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}
