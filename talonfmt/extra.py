import collections.abc
import re

from tree_sitter_talon import Node
from tree_sitter_talon import TalonBlock as TalonBlock
from tree_sitter_talon import TalonCommandDeclaration as TalonCommandDeclaration
from tree_sitter_talon import TalonComment as TalonComment
from tree_sitter_talon import TalonImplicitString as TalonImplicitString
from tree_sitter_talon import TalonMatches as TalonMatches


def _TalonBlock_with_comments(
    self: TalonBlock, comments: collections.abc.Iterable[TalonComment]
) -> TalonBlock:
    return TalonBlock(
        text=self.text,
        type_name=self.type_name,
        start_position=self.start_position,
        end_position=self.end_position,
        children=[*comments, *self.children],
    )


setattr(TalonBlock, "with_comments", _TalonBlock_with_comments)


def _TalonCommandDeclaration_is_short(self: TalonCommandDeclaration) -> bool:
    return len(self.children) + len(self.script.children) == 1


setattr(TalonCommandDeclaration, "is_short", _TalonCommandDeclaration_is_short)


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _TalonComment_assert_equivalent(self: TalonComment, other: Node):
    assert isinstance(other, TalonComment)
    assert _collapse_whitespace(self.text) == _collapse_whitespace(other.text)


setattr(TalonComment, "assert_equivalent", _TalonComment_assert_equivalent)


def _TalonImplicitString_assert_equivalent(self: TalonImplicitString, other: Node):
    assert isinstance(other, TalonImplicitString)
    assert self.text.strip() == other.text.strip()


setattr(
    TalonImplicitString, "assert_equivalent", _TalonImplicitString_assert_equivalent
)


def _TalonMatches_is_explicit(self: TalonMatches) -> bool:
    return self.text == "-" or self.text.endswith("\n-")


setattr(TalonMatches, "is_explicit", _TalonMatches_is_explicit)


def _TalonMatches___bool__(self: TalonMatches) -> bool:
    return bool(self.children)


setattr(TalonMatches, "__bool__", _TalonMatches___bool__)