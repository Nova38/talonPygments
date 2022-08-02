import dataclasses
import itertools
from collections.abc import Iterable, Iterator, Sequence
from functools import singledispatchmethod
from typing import Optional, TypeVar, Union, cast

import more_itertools
from doc_printer import (
    Doc,
    DocLike,
    Empty,
    Fail,
    Line,
    Space,
    Text,
    alt,
    angles,
    braces,
    brackets,
    cat,
    create_tables,
    double_quote,
    nest,
    parens,
    row,
)
from tree_sitter_talon import (
    Branch,
    Node,
    TalonAction,
    TalonAnd,
    TalonArgumentList,
    TalonAssignment,
    TalonBinaryOperator,
    TalonBlock,
    TalonCapture,
    TalonChoice,
    TalonCommand,
    TalonComment,
    TalonContext,
    TalonDocstring,
    TalonEndAnchor,
    TalonError,
    TalonExpression,
    TalonFloat,
    TalonIdentifier,
    TalonImplicitString,
    TalonIncludeTag,
    TalonInteger,
    TalonInterpolation,
    TalonKeyAction,
    TalonList,
    TalonMatch,
    TalonNot,
    TalonNumber,
    TalonOperator,
    TalonOptional,
    TalonOr,
    TalonParenthesizedExpression,
    TalonParenthesizedRule,
    TalonRegexEscapeSequence,
    TalonRepeat,
    TalonRepeat1,
    TalonRule,
    TalonSeq,
    TalonSettings,
    TalonSleepAction,
    TalonSourceFile,
    TalonStartAnchor,
    TalonString,
    TalonStringContent,
    TalonStringEscapeSequence,
    TalonVariable,
    TalonWord,
)

from .parse_error import ParseError

TalonBlockLevelMatch = Union[
    TalonAnd,
    TalonNot,
    TalonMatch,
    TalonOr,
]

TalonBlockLevel = Union[
    TalonSourceFile,
    TalonContext,
    TalonIncludeTag,
    TalonSettings,
    TalonCommand,
    TalonBlock,
    TalonAssignment,
    TalonExpression,
    TalonComment,
    TalonDocstring,
]

NodeVar = TypeVar("NodeVar", bound=Node)


def is_short_command(node: TalonCommand) -> bool:
    return len(node.children) + len(node.script.children) == 1


def block_with_comments(
    comments: Iterable[TalonComment], block: TalonBlock
) -> TalonBlock:
    return TalonBlock(
        text=block.text,
        type_name=block.type_name,
        start_position=block.start_position,
        end_position=block.end_position,
        children=[*comments, *block.children],
    )


@dataclasses.dataclass
class TalonFormatter:
    indent_size: int
    align_match_context: Union[bool, int]
    align_short_commands: Union[bool, int]

    @singledispatchmethod
    def format(self, node: Node) -> Doc:
        """
        Format any node as a document.
        """
        # NOTE: these should implement format_block
        if isinstance(
            node,
            (
                TalonSourceFile,
                TalonContext,
                TalonIncludeTag,
                TalonSettings,
                TalonCommand,
                TalonBlock,
                TalonAssignment,
                TalonExpression,
            ),
        ):
            return Line.join(self.format_block(node))
        elif isinstance(node, TalonError):
            raise ParseError(node)
        else:
            raise TypeError(type(node))

    @singledispatchmethod
    def format_block(self, node: TalonBlockLevel) -> Iterator[Doc]:
        """
        Format any block-level node as a series of lines.
        """
        if isinstance(node, (TalonComment, TalonDocstring)):
            yield self.format(node)
        elif isinstance(node, (TalonAnd, TalonNot, TalonMatch, TalonOr)):
            yield from self.format_block_match(node, under_and=False, under_not=False)
        elif isinstance(node, TalonError):
            raise ParseError(node)
        else:
            raise TypeError(type(node))

    @singledispatchmethod
    def format_block_match(
        self,
        match: TalonBlockLevelMatch,
        *,
        under_and: bool,
        under_not: bool,
    ) -> Iterator[Doc]:
        """
        Format any match statement or comment as a series of lines.
        """
        if isinstance(match, TalonError):
            raise ParseError(match)
        else:
            raise TypeError(type(match))

    def format_children(self, children: Iterable[Node]) -> Iterator[Doc]:
        for child in self.store_comments(children, node_type=Node):
            if isinstance(child, Iterable):
                yield from self.format_children(child)
            else:
                yield self.format(child)

    ###########################################################################
    # Format: Source Files
    ###########################################################################

    @format_block.register
    def _(self, node: TalonSourceFile) -> Iterator[Doc]:
        # Used to emit the context header separator.
        in_header: bool = True

        # Used to buffer comments to ensure that they're split correctly
        # between the header and body.
        comment_buffer: list[Doc] = []

        def clear_comment_buffer() -> Iterator[Doc]:
            if comment_buffer:
                yield from comment_buffer
                comment_buffer.clear()

        if self.align_short_commands is True:
            # Used to buffer short commands to group them as tables.
            short_command_buffer: list[Doc] = []

            def clear_short_command_buffer() -> Iterator[Doc]:
                if short_command_buffer:
                    yield from create_tables(iter(short_command_buffer))
                    short_command_buffer.clear()

        for child in node.children:
            if in_header and isinstance(child, TalonComment):
                comment_buffer.append(self.format(child))
            elif isinstance(child, TalonContext):
                assert in_header
                yield from clear_comment_buffer()
                yield from self.format_block(child)
            else:
                # NOTE: first body-only node, end the context header
                if in_header and isinstance(
                    child, (TalonIncludeTag, TalonSettings, TalonCommand)
                ):
                    yield Text("-")
                    yield from clear_comment_buffer()
                    in_header = False

                if self.align_short_commands is True:
                    if isinstance(child, TalonCommand) and is_short_command(child):
                        # NOTE: buffer short command
                        short_command_buffer.extend(self.format_block(child))
                    else:
                        # NOTE: long command or other node, clear short command buffer
                        yield from clear_short_command_buffer()
                        yield from self.format_block(child)
                else:
                    yield from self.format_block(child)

        # NOTE: no body-only node, end the context header
        if in_header:
            yield Text("-")
            yield from clear_comment_buffer()

        # NOTE: clear remaining short commands in buffer
        if self.align_short_commands is True:
            yield from clear_short_command_buffer()

    ###########################################################################
    # Format: Context Header
    ###########################################################################

    @format_block.register
    def _(self, node: TalonContext) -> Iterator[Doc]:
        for child in node.children:
            lines = list(self.format_block(child))
            yield from self.get_formatted_comments()
            yield from lines

    @format_block_match.register
    def _(self, match: TalonAnd, under_and: bool, under_not: bool) -> Iterator[Doc]:
        for child in match.children:
            if isinstance(child, TalonComment):
                yield from self.format_block(child)
            else:
                yield from self.format_block_match(child, under_and, under_not)
                under_and = True

    @format_block_match.register
    def _(self, match: TalonNot, under_and: bool, under_not: bool) -> Iterator[Doc]:
        for child in match.children:
            if isinstance(child, TalonComment):
                yield from self.format_block(child)
            else:
                yield from self.format_block_match(child, under_and, under_not)
                under_not = True

    @format_block_match.register
    def _(self, match: TalonOr, under_and: bool, under_not: bool) -> Iterator[Doc]:
        for child in match.children:
            if isinstance(child, TalonComment):
                yield from self.format_block(child)
            else:
                lines = list(self.format_block_match(child, under_and, under_not))
                yield from self.get_formatted_comments()
                yield from lines

    @format_block_match.register
    def _(self, match: TalonMatch, under_and: bool, under_not: bool) -> Iterator[Doc]:
        self.assert_only_comments(match.children)
        match_keywords = self.format_match_keywords(under_and, under_not)
        key = cat(match_keywords, self.format(match.key))
        pattern = self.format(match.pattern)
        yield alt(self.format_match_alternatives(key, pattern))

    def format_match_keywords(self, under_and: bool, under_not: bool) -> Iterator[Doc]:
        if under_and:
            yield Text("and")
            yield Space
        if under_not:
            yield Text("not")
            yield Space

    def format_match_alternatives(self, key: Doc, pattern: Doc) -> Iterator[Doc]:
        # Standard
        yield key / ":" // pattern

        # Aligned alternative
        if self.align_match_context:
            if self.align_match_context is True:
                yield row(
                    key / ":",
                    pattern,
                    table_type="match",
                )
            else:
                yield row(
                    key / ":",
                    pattern,
                    table_type="match",
                    min_col_widths=(self.align_match_context,),
                )

    ###########################################################################
    # Format: Tag Includes
    ###########################################################################

    @format_block.register
    def _(self, node: TalonIncludeTag) -> Iterator[Doc]:
        self.assert_only_comments(node.children)
        yield from self.get_formatted_comments()
        yield "tag():" // self.format(node.tag)

    ###########################################################################
    # Format: Settings
    ###########################################################################

    @format_block.register
    def _(self, node: TalonSettings) -> Iterator[Doc]:
        block = self.get_node_with_type(node.children, node_type=TalonBlock)
        block = block_with_comments(self.get_comments(), block)
        yield "settings():" // nest(self.indent_size, Line, self.format(block))

    ###########################################################################
    # Format: Commands
    ###########################################################################

    @format_block.register
    def _(self, node: TalonCommand) -> Iterator[Doc]:
        rule = self.format(node.rule)
        yield from self.get_formatted_comments()

        # Merge comments on this node into the block node.
        block = block_with_comments(node.children, node.script)
        script = self.format(block)

        # (1): a line-break after the rule, e.g.,
        #
        # select camel left:
        #     user.extend_camel_left()
        #
        alt1 = cat(
            rule / ":",
            nest(self.indent_size, Line, script, Line),
        )

        # (2): the rule and a single-line talon script on the same line, e.g.,
        #
        # select camel left: user.extend_camel_left()
        #
        if len(block.children) == 1:
            alt2 = self.format_short_command(rule, script)
        else:
            alt2 = Fail

        yield alt1 | alt2

    def format_short_command(self, rule: Doc, script: Doc) -> Doc:
        if self.align_short_commands:
            if self.align_short_commands is True:
                return row(
                    rule / ":",
                    script,
                    table_type="command",
                )
            else:
                return row(
                    rule / ":",
                    script,
                    table_type="command",
                    min_col_widths=(self.align_short_commands,),
                )
        else:
            return rule / ":" // script

    ###########################################################################
    # Format: Statements
    ###########################################################################

    @format_block.register
    def _(self, node: TalonBlock) -> Iterator[Doc]:
        for child in node.children:
            for line in self.format_block(child):
                yield from self.get_formatted_comments()
                yield line

    @format_block.register
    def _(self, node: TalonAssignment) -> Iterator[Doc]:
        self.assert_only_comments(node.children)
        yield self.format(node.left) // "=" // self.format(node.right)

    @format_block.register
    def _(self, node: TalonExpression) -> Iterator[Doc]:
        self.assert_only_comments(node.children)
        yield self.format(node.expression)

    ###########################################################################
    # Format: Expressions
    ###########################################################################

    @format.register
    def _(self, node: TalonAction) -> Doc:
        self.assert_only_comments(node.children)
        return self.format(node.action_name) / parens(self.format(node.arguments))

    @format.register
    def _(self, node: TalonArgumentList) -> Doc:
        return ("," / Space).join(self.format_children(node.children))

    @format.register
    def _(self, node: TalonBinaryOperator) -> Doc:
        self.assert_only_comments(node.children)
        return (
            self.format(node.left)
            // self.format(node.operator)
            // self.format(node.right)
        )

    @format.register
    def _(self, node: TalonIdentifier) -> Doc:
        return Text.words(node.text, collapse_whitespace=True)

    @format.register
    def _(self, node: TalonKeyAction) -> Doc:
        self.assert_only_comments(node.children)
        return "key" / parens(self.format(node.arguments))

    @format.register
    def _(self, node: TalonOperator) -> Doc:
        return Text.words(node.text, collapse_whitespace=True)

    @format.register
    def _(self, node: TalonParenthesizedExpression) -> Doc:
        return parens(self.format(self.get_node(node.children)))

    @format.register
    def _(self, node: TalonRegexEscapeSequence) -> Doc:
        if node.children:
            return braces(self.format_children(node.children))
        else:
            return braces(Empty)

    @format.register
    def _(self, node: TalonSleepAction) -> Doc:
        self.assert_only_comments(node.children)
        return "sleep" / parens(self.format(node.arguments))

    @format.register
    def _(self, node: TalonVariable) -> Doc:
        self.assert_only_comments(node.children)
        return self.format(node.variable_name)

    ###########################################################################
    # Format: Numbers
    ###########################################################################

    @format.register
    def _(self, node: TalonFloat) -> Doc:
        return Text.words(node.text.strip(), collapse_whitespace=True)

    @format.register
    def _(self, node: TalonInteger) -> Doc:
        return Text.words(node.text.strip(), collapse_whitespace=True)

    @format.register
    def _(self, node: TalonNumber) -> Doc:
        return self.format(self.get_node(node.children))

    ###########################################################################
    # Format: Strings
    ###########################################################################

    @format.register
    def _(self, node: TalonImplicitString) -> Doc:
        return Text.words(node.text.strip(), collapse_whitespace=True)

    @format.register
    def _(self, node: TalonInterpolation) -> Doc:
        return self.format(self.get_node(node.children))

    @format.register
    def _(self, node: TalonString) -> Doc:
        return double_quote(self.format_children(node.children))

    @format.register
    def _(self, node: TalonStringContent) -> Doc:
        return Text.words(node.text)

    @format.register
    def _(self, node: TalonStringEscapeSequence) -> Doc:
        return Text.words(node.text)

    ###########################################################################
    # Format: Rules
    ###########################################################################

    @format.register
    def _(self, node: TalonCapture) -> Doc:
        self.assert_only_comments(node.children)
        return angles(self.format(node.capture_name))

    @format.register
    def _(self, node: TalonChoice) -> Doc:
        children = self.format_children(node.children)
        operator = Space / "|" / Space
        return operator.join(children)

    @format.register
    def _(self, node: TalonEndAnchor) -> Doc:
        return Text("$")

    @format.register
    def _(self, node: TalonList) -> Doc:
        self.assert_only_comments(node.children)
        return braces(self.format(node.list_name))

    @format.register
    def _(self, node: TalonOptional) -> Doc:
        child = self.get_node(node.children)
        return brackets(self.format(child))

    @format.register
    def _(self, node: TalonParenthesizedRule) -> Doc:
        child = self.get_node(node.children)
        return parens(self.format(child))

    @format.register
    def _(self, node: TalonRepeat) -> Doc:
        child = self.get_node(node.children)
        return self.format(child) / "*"

    @format.register
    def _(self, node: TalonRepeat1) -> Doc:
        return self.format(self.get_node(node.children)) / "+"

    @format.register
    def _(self, node: TalonRule) -> Doc:
        return cat(self.format_children(node.children))

    @format.register
    def _(self, node: TalonSeq) -> Doc:
        return Space.join(self.format_children(node.children))

    @format.register
    def _(self, node: TalonStartAnchor) -> Doc:
        return Text("^")

    @format.register
    def _(self, node: TalonWord) -> Doc:
        return Text.words(node.text)

    ###########################################################################
    # Format: Comments
    ###########################################################################

    @format.register
    def _(self, node: TalonComment) -> Doc:
        comment = node.text.lstrip("#")
        return "#" / Text.words(comment, collapse_whitespace=False)

    @format.register
    def _(self, node: TalonDocstring) -> Doc:
        comment = node.text.lstrip("#")
        return "###" / Text.words(comment, collapse_whitespace=False)

    # Used to buffer comments encountered inline, e.g., inside a binary operator
    _comment_buffer: list[TalonComment] = dataclasses.field(
        default_factory=list, init=False
    )

    def store_comments(
        self,
        children: Iterable[Union[TalonComment, NodeVar]],
        *,
        node_type: type[NodeVar],
    ) -> Iterator[NodeVar]:
        for child in children:
            if isinstance(child, TalonComment):
                self._comment_buffer.append(child)
            elif isinstance(child, node_type):
                yield child
            else:
                raise TypeError(type(child))

    def get_comments(self) -> Iterator[TalonComment]:
        try:
            yield from self._comment_buffer
        finally:
            self._comment_buffer.clear()

    def get_formatted_comments(self) -> Iterator[Doc]:
        yield from map(self.format, self.get_comments())

    def assert_only_comments(self, children: Iterable[TalonComment]) -> None:
        rest = tuple(self.store_comments(children, node_type=TalonComment))
        assert (
            len(rest) == 0
        ), f"There should be no non-comment nodes, found {tuple(node.type_name for node in rest)}:\n{rest}"

    def get_node(self, children: Iterable[Node]) -> Node:
        return self.get_node_with_type(children, node_type=Node)

    def get_node_with_type(
        self,
        children: Iterable[Union[NodeVar, TalonComment]],
        *,
        node_type: type[NodeVar],
    ) -> NodeVar:
        rest = tuple(self.store_comments(children, node_type=node_type))
        assert (
            len(rest) == 1
        ), f"There should be only one non-comment child, found {tuple(node.type_name for node in rest)}:\n{rest}"
        return next(iter(rest))
