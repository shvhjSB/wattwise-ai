/**
 * A printable report of a check-up page (T069): a button that opens the browser's print dialog
 * (save as PDF or print), and a header that only appears on paper, saying where the figures came
 * from. Forms and navigation are hidden in print by `print:hidden` on those elements.
 */
export function PrintButton() {
  return (
    <button
      type="button"
      onClick={() => {
        window.print();
      }}
      className="rounded-md border border-edge px-4 py-2 text-sm font-semibold print:hidden"
    >
      Print this report
    </button>
  );
}

export function PrintHeader({ title, source }: { title: string; source: string }) {
  const printed = new Date().toISOString().slice(0, 10);
  return (
    <div className="hidden space-y-1 border-b border-line pb-2 print:block">
      <p className="text-lg font-semibold">WattWise electricity check-up: {title}</p>
      <p className="text-xs">
        {source} Computed in the browser; nothing was sent or stored. Printed {printed}. Potential
        savings are hypothetical, and an unusual period is not confirmed waste.
      </p>
    </div>
  );
}
