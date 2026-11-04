import { useId } from "react";

const colors = ["#e9a35b", "#d98182", "#a78bca", "#81b4df", "#78b9b0", "#9bc88a"];
const names = ["Amber", "Rose", "Lilac", "Blue", "Teal", "Green"];

/** Presets for a quick choice; the text field preserves existing named colors. */
export function ColorPicker({ value, onChange }: { value: string; onChange: (color: string) => void }) {
  const name = useId();
  return <div className="color-picker">
    <fieldset className="color-swatches"><legend className="sr-only">Tag color</legend>
      <label className="color-swatch color-swatch--none"><input type="radio" name={name} checked={!value} onChange={() => onChange("")} /><span aria-hidden="true">∅</span><span className="sr-only">No color</span></label>
      {colors.map((color, i) => <label key={color} className={`color-swatch color-swatch--${i}`}><input type="radio" name={name} checked={value.toLowerCase() === color} onChange={() => onChange(color)} /><span className="sr-only">{names[i]}</span></label>)}
    </fieldset>
    <div className="color-custom"><input type="color" aria-label="Choose a custom color" value={/^#[0-9a-f]{6}$/i.test(value) ? value : "#e9a35b"} onChange={(event) => onChange(event.target.value)} /><input id="id_color" type="text" placeholder="Custom color or name" maxLength={20} value={value} onChange={(event) => onChange(event.target.value)} /></div>
  </div>;
}
