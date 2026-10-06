import { render, screen } from "@testing-library/react";
import Markdown from "./Markdown";

it("renders experiment comparisons as a table", () => {
  render(<Markdown content={"| Method | Score |\n| --- | --- |\n| Baseline | 42 |"} />);
  expect(screen.getByRole("table")).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "42" })).toBeInTheDocument();
});

it("preserves pseudocode line breaks without interpreting headings", () => {
  const { container } = render(<Markdown content={"```python\n# Step one\nx = 1\n```"} />);
  expect(container.querySelector("pre code")?.textContent).toBe("# Step one\nx = 1");
  expect(screen.queryByRole("heading")).not.toBeInTheDocument();
});
