import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/** 把助手回复里的 markdown 渲染出来（表格、列表、代码块、链接）。 */
export function MarkdownText({ text }: { text: string }) {
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>
        ),
        table: ({ children }) => (
          <div className="md-table-wrap"><table>{children}</table></div>
        ),
      }}
    >
      {text}
    </Markdown>
  )
}
