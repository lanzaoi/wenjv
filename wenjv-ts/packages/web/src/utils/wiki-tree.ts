import type { WikiTreeNode } from '../stores/wiki';

export interface WikiTreeOption {
  id: number;
  title: string;
  prefix: string;
}

/** Flatten nested Wiki tree nodes into indented select options. */
export function flattenWikiTreeOptions(nodes: WikiTreeNode[], depth = 0): WikiTreeOption[] {
  const out: WikiTreeOption[] = [];
  for (const node of nodes) {
    out.push({
      id: node.id,
      title: node.title,
      prefix: depth > 0 ? `${'  '.repeat(depth)}└ ` : '',
    });
    if (node.children && node.children.length > 0) {
      out.push(...flattenWikiTreeOptions(node.children, depth + 1));
    }
  }
  return out;
}
