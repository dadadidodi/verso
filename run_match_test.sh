#!/usr/bin/env bash

set -u

if ! python3 chapter_debug.py --zh "data/CnMiddleMarch.epub" --en "data/EnMiddlemarch.epub" --result-out result.txt; then
  echo "测试失败（章节匹配执行失败）" >&2
  exit 1
fi

if ! cmp -s result.txt ref.txt; then
  echo "测试失败（章节匹配与 ref.txt 不一致，已保留 result.txt）" >&2
  exit 1
fi

if ! python3 paragraph_debug.py --zh "data/CnMiddleMarch.epub" --en "data/EnMiddlemarch.epub" --result-out paragraph_result.txt; then
  echo "测试失败（段落对齐执行失败）" >&2
  exit 1
fi

if [ -f "paragraph_ref.txt" ] && ! cmp -s paragraph_result.txt paragraph_ref.txt; then
  echo "测试失败（段落对齐与 paragraph_ref.txt 不一致，已保留 paragraph_result.txt）" >&2
  exit 1
fi

rm -f result.txt paragraph_result.txt
echo "测试成功（已删除 result.txt / paragraph_result.txt）"
exit 0
