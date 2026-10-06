import { render, screen, waitFor } from "@testing-library/react";
import Markdown from "./Markdown";

it("renders experiment comparisons as a table", () => {
  render(<Markdown content={"| Method | Score |\n| --- | --- |\n| Baseline | 42 |"} />);
  expect(screen.getByRole("table")).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "42" })).toBeInTheDocument();
});

it("renders math without losing subscripts and preserves code literals", async () => {
  const { container } = render(<Markdown content={String.raw`Inline $x_i^*$ and \(\pi_{ref}\).

$$
\frac{a_i}{b_j}
$$

` + "`$x_i$`"} />);
  await waitFor(() => expect(container.querySelectorAll(".katex")).toHaveLength(3));
  expect(container.querySelector("annotation")?.textContent).toBe("x_i^*");
  expect(container.querySelector("code")?.textContent).toBe("$x_i$");
  expect(container.querySelector(".math-block")).toBeInTheDocument();
});

it("preserves pseudocode line breaks without interpreting headings", () => {
  const { container } = render(<Markdown content={"```python\n# Step one\nx = 1\n```"} />);
  expect(container.querySelector("pre code")?.textContent).toBe("# Step one\nx = 1");
  expect(screen.queryByRole("heading")).not.toBeInTheDocument();
});
