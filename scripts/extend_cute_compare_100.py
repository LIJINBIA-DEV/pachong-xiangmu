"""Compatibility entry: select 100 images exclusively from verified Jev passes.

The previous mixed 49+51 report is preserved in its original directory.
"""
from select_jev_passed_compare import DEFAULT_OUT, build


if __name__ == '__main__':
    build(DEFAULT_OUT)
