/**
 * remark 插件：将 ^^text^^ 语法转换为 <sup>text</sup>
 */
import type {Plugin} from 'unified';
import {visit} from 'unist-util-visit';
import type {Parent, Text, Html} from 'mdast';

const RE = /\^\^(.+?)\^\^/g;

const remarkSuperscript: Plugin = () => {
  return (tree) => {
    visit(tree, 'text', (node: Text, index: number | undefined, parent: Parent | undefined) => {
      if (!parent || index === undefined) return;
      if (!RE.test(node.value)) return;
      RE.lastIndex = 0;

      const children: (Text | Html)[] = [];
      let last = 0;
      let match: RegExpExecArray | null;

      while ((match = RE.exec(node.value)) !== null) {
        if (match.index > last) {
          children.push({type: 'text', value: node.value.slice(last, match.index)});
        }
        children.push({type: 'html', value: `<sup>${match[1]}</sup>`});
        last = match.index + match[0].length;
      }

      if (last < node.value.length) {
        children.push({type: 'text', value: node.value.slice(last)});
      }

      parent.children.splice(index, 1, ...children);
      return index + children.length;
    });
  };
};

export default remarkSuperscript;
