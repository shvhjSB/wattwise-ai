import { useState, type SyntheticEvent } from 'react';

import { addAlertFeedback, FEEDBACK_LABELS, type FeedbackLabel } from '../../api/alerts';
import { ApiError } from '../../api/client';
import { sentence } from './format';

const DESCRIPTIONS: Record<FeedbackLabel, string> = {
  confirmed_waste: 'A reviewer judges that avoidable energy use occurred.',
  expected_behaviour: 'The reading is unusual but expected for this building.',
  sensor_or_data_fault: 'The event comes from the meter, sensor, or data pipeline.',
  needs_investigation: 'Keep it open while more evidence is gathered.',
};

export function FeedbackForm({ alertId, onSaved }: { alertId: number; onSaved: () => void }) {
  const [label, setLabel] = useState<FeedbackLabel>('needs_investigation');
  const [note, setNote] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  const [error, setError] = useState<string | null>(null);

  const submit = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    setStatus('saving');
    setError(null);
    addAlertFeedback(alertId, {
      label,
      ...(note.trim() ? { note: note.trim() } : {}),
      ...(reviewer.trim() ? { reviewer: reviewer.trim() } : {}),
    }).then(
      () => {
        setStatus('saved');
        setNote('');
        onSaved();
      },
      (reason: unknown) => {
        setStatus('idle');
        setError(reason instanceof ApiError ? reason.message : 'The review could not be recorded.');
      },
    );
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold">Record a review</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {FEEDBACK_LABELS.map((value) => (
            <label
              key={value}
              htmlFor={`feedback-${value}`}
              className={`cursor-pointer rounded-lg border p-3 text-sm ${label === value ? 'border-accent bg-accent-soft' : 'border-edge bg-raised'}`}
            >
              <span className="sr-only">Feedback option: </span>
              <span className="flex items-start gap-2">
                <input
                  id={`feedback-${value}`}
                  type="radio"
                  name="feedback-label"
                  value={value}
                  checked={label === value}
                  onChange={() => {
                    setLabel(value);
                    setStatus('idle');
                  }}
                  className="mt-1 accent-accent"
                />
                <span>
                  <span className="block font-medium">{sentence(value)}</span>
                  <span className="mt-0.5 block text-xs text-muted">{DESCRIPTIONS[value]}</span>
                </span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          Reviewer <span className="text-muted">(optional)</span>
          <input
            value={reviewer}
            maxLength={100}
            onChange={(event) => {
              setReviewer(event.target.value);
              setStatus('idle');
            }}
            className="mt-1 w-full rounded-md border border-edge bg-raised px-3 py-2"
          />
        </label>
        <label className="text-sm sm:row-span-2">
          Note <span className="text-muted">(optional)</span>
          <textarea
            value={note}
            maxLength={2000}
            rows={4}
            onChange={(event) => {
              setNote(event.target.value);
              setStatus('idle');
            }}
            className="mt-1 w-full rounded-md border border-edge bg-raised px-3 py-2"
          />
        </label>
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={status === 'saving'}
            className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-ink disabled:opacity-50"
          >
            {status === 'saving' ? 'Saving...' : 'Save review'}
          </button>
          {status === 'saved' ? (
            <span role="status" className="text-sm text-success">
              Review saved.
            </span>
          ) : null}
        </div>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
      <p className="text-xs text-muted">
        Reviews are kept as a history. Saving one does not retrain or automatically change the
        model.
      </p>
    </form>
  );
}
