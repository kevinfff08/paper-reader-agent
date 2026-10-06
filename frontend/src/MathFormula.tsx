import { useMemo } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";

export default function MathFormula({ source, display }: { source: string; display: boolean }) {
  const markup = useMemo(() => katex.renderToString(source, {
    displayMode: display, throwOnError: false, trust: false,
    maxExpand: 1000, maxSize: 20, strict: "ignore", macros: {},
  }), [source, display]);
  return <span className={display ? "math-block" : "math-inline"} dangerouslySetInnerHTML={{ __html: markup }} />;
}
