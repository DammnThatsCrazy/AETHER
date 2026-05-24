import DocPage from './components/DocPage';
import OverviewContent, { frontmatter as overviewFm } from './content/overview.mdx';

export default function App() {
  return (
    <DocPage Content={OverviewContent} frontmatter={overviewFm} />
  );
}
