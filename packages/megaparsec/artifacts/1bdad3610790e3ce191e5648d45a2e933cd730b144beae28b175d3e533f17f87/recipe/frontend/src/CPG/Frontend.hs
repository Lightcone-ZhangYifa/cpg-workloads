{-# LANGUAGE OverloadedStrings #-}

-- | A deliberately bounded compiler-frontend fixture.  This module preserves
-- Megaparsec's typed errors and source positions; it is not a language evaluator.
module CPG.Frontend
  ( Diagnostic (..),
    SourcePoint (..),
    SourceSpan (..),
    Expr (..),
    Statement (..),
    ParseResult,
    Json (..),
    parseProgram,
    resultJson,
    renderJson,
    versionJson,
    inputErrorJson,
  )
where

import Control.Monad (void, when)
import Control.Monad.Combinators.Expr (Operator (..), makeExprParser)
import qualified Data.ByteString as BS
import Data.Char (GeneralCategory (..), generalCategory, isAlphaNum, isLetter, ord)
import Data.Foldable (toList)
import qualified Data.List.NonEmpty as NE
import qualified Data.Set as Set
import Data.Text (Text)
import qualified Data.Text as T
import qualified Data.Text.Encoding as TE
import Numeric (showHex)
import Text.Megaparsec
import Text.Megaparsec.Char (char, space1, string)
import qualified Text.Megaparsec.Char.Lexer as L

-- | Distinct constructors remain distinct in both the Haskell and JSON APIs.
-- The bound applies to the unsigned decimal token, before unary operators.
data Diagnostic
  = ReservedIdentifier Text
  | IntegerOutOfRange Text Text Integer
  deriving (Eq, Ord, Show)

instance ShowErrorComponent Diagnostic where
  showErrorComponent (ReservedIdentifier name) =
    "reserved word " ++ show (T.unpack name) ++ " cannot be used as an identifier"
  showErrorComponent (IntegerOutOfRange raw _ upper) =
    "integer literal " ++ T.unpack raw ++ " exceeds the fixture's maximum " ++ show upper
  errorComponentLen (ReservedIdentifier name) = max 1 (T.length name)
  errorComponentLen (IntegerOutOfRange raw _ _) = max 1 (T.length raw)

data SourcePoint = SourcePoint
  { pointOffset :: Int,
    pointPosition :: SourcePos
  }
  deriving (Eq, Ord, Show)

-- | The end is exclusive.  Neither endpoint includes trailing whitespace.
data SourceSpan = SourceSpan
  { spanStart :: SourcePoint,
    spanEnd :: SourcePoint
  }
  deriving (Eq, Ord, Show)

data Expr
  = IntegerLiteral SourceSpan Text Integer
  | Variable SourceSpan Text
  | Unary SourceSpan Text SourceSpan Expr
  | Binary SourceSpan Text SourceSpan Expr Expr
  | Parenthesized SourceSpan Expr
  deriving (Eq, Show)

data Statement = LetStatement SourceSpan SourceSpan Text Expr
  deriving (Eq, Show)

type Parser = Parsec Diagnostic Text

type ParseResult = Either (ParseErrorBundle Text Diagnostic) [Statement]

-- | A tiny JSON value type avoids introducing a second parser/JSON dependency.
-- Integer values are arbitrary precision in this representation.
data Json
  = JObject [(String, Json)]
  | JArray [Json]
  | JString String
  | JNumber Integer
  | JBool Bool
  | JNull
  deriving (Eq, Show)

fixtureVersion, megaparsecVersion :: String
fixtureVersion = "0.1.0.0"
megaparsecVersion = "9.8.3"

integerUpperBound :: Integer
integerUpperBound = 2147483647

integerUpperBoundText :: Text
integerUpperBoundText = "2147483647"

reservedWords :: Set.Set Text
reservedWords = Set.fromList ["let", "if", "then", "else", "while", "return", "true", "false"]

isIdentifierStart, isIdentifierContinue :: Char -> Bool
isIdentifierStart c = c == '_' || isLetter c
isIdentifierContinue c =
  c == '_'
    || isAlphaNum c
    || generalCategory c `elem` [NonSpacingMark, SpacingCombiningMark, EnclosingMark]

spaceConsumer :: Parser ()
spaceConsumer = L.space space1 (L.skipLineComment "//") (L.skipBlockCommentNested "/*" "*/")

point :: Parser SourcePoint
point = SourcePoint <$> getOffset <*> getSourcePos

withSpan :: Parser a -> Parser (SourceSpan, a)
withSpan parser = do
  start <- point
  value <- parser
  end <- point
  pure (SourceSpan start end, value)

-- Capture the token's end before consuming its trailing trivia.
tokenWithSpan :: Parser a -> Parser (SourceSpan, a)
tokenWithSpan parser = withSpan parser <* spaceConsumer

symbolSpan :: Text -> Parser SourceSpan
symbolSpan text = fst <$> tokenWithSpan (string text)

identifier :: Parser (SourceSpan, Text)
identifier = tokenWithSpan $ do
  start <- getOffset
  first <- satisfy isIdentifierStart <?> "identifier"
  rest <- takeWhileP (Just "identifier continuation") isIdentifierContinue
  let name = T.cons first rest
  when (Set.member name reservedWords) $
    parseError (FancyError start (Set.singleton (ErrorCustom (ReservedIdentifier name))))
  pure name

integer :: Parser Expr
integer = do
  (sourceSpan, (raw, value)) <- tokenWithSpan $ do
    start <- getOffset
    raw <- takeWhile1P (Just "decimal integer") (\c -> c >= '0' && c <= '9')
    notFollowedBy (satisfy isIdentifierContinue) <?> "integer token boundary"
    -- Check the lexical magnitude first.  Rejected million-digit input should
    -- not be converted into a giant Integer merely to produce a diagnostic.
    let withoutLeadingZeroes = T.dropWhile (== '0') raw
        decimal = if T.null withoutLeadingZeroes then "0" else withoutLeadingZeroes
        exceedsBound =
          T.length decimal > T.length integerUpperBoundText
            || (T.length decimal == T.length integerUpperBoundText && decimal > integerUpperBoundText)
    when exceedsBound $
      parseError (FancyError start (Set.singleton (ErrorCustom (IntegerOutOfRange raw decimal integerUpperBound))))
    let value = T.foldl' (\acc digit -> acc * 10 + fromIntegral (ord digit - ord '0')) 0 decimal
    pure (raw, value)
  pure (IntegerLiteral sourceSpan raw value)

variable :: Parser Expr
variable = do
  (sourceSpan, name) <- identifier
  pure (Variable sourceSpan name)

parenthesized :: Parser Expr
parenthesized = do
  opening <- symbolSpan "("
  inner <- expression
  closing <- symbolSpan ")"
  pure (Parenthesized (SourceSpan (spanStart opening) (spanEnd closing)) inner)

exprSpan :: Expr -> SourceSpan
exprSpan (IntegerLiteral sourceSpan _ _) = sourceSpan
exprSpan (Variable sourceSpan _) = sourceSpan
exprSpan (Unary sourceSpan _ _ _) = sourceSpan
exprSpan (Binary sourceSpan _ _ _ _) = sourceSpan
exprSpan (Parenthesized sourceSpan _) = sourceSpan

expression :: Parser Expr
expression = makeExprParser term operators
  where
    term = parenthesized <|> integer <|> variable <?> "expression"
    operators =
      [ [Prefix unaryOperators],
        [InfixL (binaryOperator "*"), InfixL (binaryOperator "/")],
        [InfixL (binaryOperator "+"), InfixL (binaryOperator "-")]
      ]
    unaryOperators = do
      tokens <- some ((\sourceSpan -> ("-", sourceSpan)) <$> symbolSpan "-" <|> (\sourceSpan -> ("+", sourceSpan)) <$> symbolSpan "+")
      pure $ \operand -> foldr applyUnary operand tokens
    applyUnary (operator, operatorSpan) operand =
      Unary (SourceSpan (spanStart operatorSpan) (spanEnd (exprSpan operand))) operator operatorSpan operand
    binaryOperator operator = do
      operatorSpan <- symbolSpan operator
      pure $ \left right ->
        Binary (SourceSpan (spanStart (exprSpan left)) (spanEnd (exprSpan right))) operator operatorSpan left right

statement :: Parser Statement
statement = do
  (keywordSpan, _) <- tokenWithSpan (try (string "let" <* notFollowedBy (satisfy isIdentifierContinue)) <?> "keyword 'let'")
  (nameSpan, name) <- identifier
  void (symbolSpan "=")
  value <- expression
  terminator <- symbolSpan ";"
  pure (LetStatement (SourceSpan (spanStart keywordSpan) (spanEnd terminator)) nameSpan name value)

-- | Recovery is a documented fixture policy: discard up to and including the
-- next raw semicolon, or to EOF.  It does not infer missing delimiters, execute
-- statements, or claim a grammar-independent recovery strategy.
-- The branch consumes at least one token unless it is already at EOF.
recoverStatement :: ParseError Text Diagnostic -> Parser (Maybe Statement)
recoverStatement problem = do
  registerParseError problem
  void (takeWhileP Nothing (/= ';'))
  void (optional (char ';'))
  pure Nothing

-- Unterminated leading trivia can only be recovered by draining the input.
recoverSpace :: ParseError Text Diagnostic -> Parser ()
recoverSpace problem = registerParseError problem *> void takeRest

program :: Bool -> Parser [Statement]
program recovery = loop []
  where
    loop statements = do
      if recovery then withRecovery recoverSpace spaceConsumer else spaceConsumer
      finished <- atEnd
      if finished
        then pure (reverse statements)
        else do
          next <-
            if recovery
              then withRecovery recoverStatement (Just <$> statement)
              else Just <$> statement
          loop (maybe statements (: statements) next)

-- | Registered recovered errors still produce Left; --recover never turns an
-- invalid program into a successful parse.
parseProgram :: Bool -> FilePath -> Text -> ParseResult
parseProgram recovery filename = runParser (program recovery <* eof) filename

number :: Int -> Json
number = JNumber . fromIntegral

textJson :: Text -> Json
textJson = JString . T.unpack

pointJson :: Text -> SourcePoint -> Json
pointJson input (SourcePoint offset sourcePos) =
  JObject
    [ ("offset", number offset),
      ("byte_offset", number (BS.length (TE.encodeUtf8 (T.take offset input)))),
      ("utf16_offset", number (BS.length (TE.encodeUtf16LE (T.take offset input)) `div` 2)),
      ("source_name", JString (sourceName sourcePos)),
      ("line", number (unPos (sourceLine sourcePos))),
      ("column", number (unPos (sourceColumn sourcePos)))
    ]

spanJson :: Text -> SourceSpan -> Json
spanJson input (SourceSpan start end) = JObject [("start", pointJson input start), ("end", pointJson input end), ("end_exclusive", JBool True)]

exprJson :: Text -> Expr -> Json
exprJson input expr =
  JObject $ [("kind", JString kind), ("span", spanJson input (exprSpan expr))] ++ fields
  where
    (kind, fields) = case expr of
      IntegerLiteral _ raw value -> ("IntegerLiteral", [("lexeme", textJson raw), ("value", JNumber value)])
      Variable _ name -> ("Variable", [("name", textJson name)])
      Unary _ operator operatorSpan operand ->
        ("Unary", [("operator", textJson operator), ("operator_span", spanJson input operatorSpan), ("operand", exprJson input operand)])
      Binary _ operator operatorSpan left right ->
        ("Binary", [("operator", textJson operator), ("operator_span", spanJson input operatorSpan), ("left", exprJson input left), ("right", exprJson input right)])
      Parenthesized _ inner -> ("Parenthesized", [("expression", exprJson input inner)])

statementJson :: Text -> Statement -> Json
statementJson input (LetStatement sourceSpan nameSpan name value) =
  JObject
    [ ("kind", JString "LetStatement"),
      ("span", spanJson input sourceSpan),
      ("name", textJson name),
      ("name_span", spanJson input nameSpan),
      ("value", exprJson input value)
    ]

itemJson :: ErrorItem Char -> Json
itemJson EndOfInput = JObject [("kind", JString "EndOfInput")]
itemJson (Label labelText) = JObject [("kind", JString "Label"), ("label", JString (NE.toList labelText))]
itemJson (Tokens tokens) = JObject [("kind", JString "Tokens"), ("tokens", JString (NE.toList tokens))]

diagnosticJson :: Diagnostic -> Json
diagnosticJson (ReservedIdentifier name) =
  JObject [("constructor", JString "ReservedIdentifier"), ("identifier", textJson name)]
diagnosticJson (IntegerOutOfRange raw value upper) =
  JObject
    [ ("constructor", JString "IntegerOutOfRange"),
      ("lexeme", textJson raw),
      ("value_decimal", textJson value),
      ("maximum_decimal", JString (show upper))
    ]

fancyJson :: ErrorFancy Diagnostic -> Json
fancyJson (ErrorFail message) = JObject [("kind", JString "ErrorFail"), ("message", JString message)]
fancyJson (ErrorIndentation ordering reference actual) =
  JObject
    [ ("kind", JString "ErrorIndentation"),
      ("ordering", JString (show ordering)),
      ("reference", number (unPos reference)),
      ("actual", number (unPos actual))
    ]
fancyJson (ErrorCustom diagnostic) = JObject [("kind", JString "ErrorCustom"), ("diagnostic", diagnosticJson diagnostic)]

errorJson :: Text -> PosState Text -> ParseError Text Diagnostic -> Json
errorJson input initialState problem =
  JObject $
    [ ("kind", JString kind),
      ("offset", number offset),
      ("position", pointJson input (SourcePoint offset sourcePos)),
      ("message", JString (parseErrorTextPretty problem))
    ]
      ++ fields
  where
    offset = errorOffset problem
    sourcePos = pstateSourcePos (reachOffsetNoLine offset initialState)
    (kind, fields) = case problem of
      TrivialError _ unexpected expected ->
        ("TrivialError", [("unexpected", maybe JNull itemJson unexpected), ("expected", JArray (map itemJson (Set.toAscList expected)))])
      FancyError _ details -> ("FancyError", [("details", JArray (map fancyJson (Set.toAscList details)))])

versionJson :: Json
versionJson =
  JObject
    [ ("name", JString "cpg-megaparsec-frontend"),
      ("fixture_version", JString fixtureVersion),
      ("megaparsec_version", JString megaparsecVersion),
      ("language", JString "cpg-let-v1"),
      ("schema_version", JNumber 1)
    ]

resultJson :: Bool -> FilePath -> Text -> ParseResult -> Json
resultJson recovery filename input result =
  JObject $
    [ ("schema_version", JNumber 1),
      ("fixture_version", JString fixtureVersion),
      ("megaparsec_version", JString megaparsecVersion),
      ("language", JString "cpg-let-v1"),
      ("recovery_requested", JBool recovery),
      ( "source",
        JObject
          [ ("name", JString filename),
            ("encoding", JString "UTF-8"),
            ("offset_unit", JString "unicode_codepoint"),
            ("byte_offset_unit", JString "utf8_byte"),
            ("utf16_offset_unit", JString "utf16_codeunit"),
            ("column_unit", JString "display_cell"),
            ("offset_base", JNumber 0),
            ("line_column_base", JNumber 1),
            ("tab_width", JNumber 8),
            ("token_count", number (T.length input)),
            ("byte_count", number (BS.length (TE.encodeUtf8 input))),
            ("utf16_count", number (BS.length (TE.encodeUtf16LE input) `div` 2))
          ]
      )
    ]
      ++ case result of
        Right statements ->
          [ ("ok", JBool True),
            ("ast", JArray (map (statementJson input) statements)),
            ("errors", JArray [])
          ]
        Left bundle ->
          [ ("ok", JBool False),
            ("ast", JNull),
            ("errors", JArray (map (errorJson input (bundlePosState bundle)) (toList (bundleErrors bundle)))),
            ("pretty", JString (errorBundlePretty bundle))
          ]

inputErrorJson :: String -> String -> Json
inputErrorJson code message =
  JObject
    [ ("schema_version", JNumber 1),
      ("ok", JBool False),
      ("kind", JString "InputError"),
      ("code", JString code),
      ("message", JString message)
    ]

renderJson :: Json -> String
renderJson (JObject fields) = "{" ++ commaJoin [quote key ++ ":" ++ renderJson value | (key, value) <- fields] ++ "}"
renderJson (JArray values) = "[" ++ commaJoin (map renderJson values) ++ "]"
renderJson (JString value) = quote value
renderJson (JNumber value) = show value
renderJson (JBool True) = "true"
renderJson (JBool False) = "false"
renderJson JNull = "null"

commaJoin :: [String] -> String
commaJoin [] = ""
commaJoin [item] = item
commaJoin (item : rest) = item ++ "," ++ commaJoin rest

quote :: String -> String
quote value = '"' : concatMap escape value ++ "\""
  where
    escape '"' = "\\\""
    escape '\\' = "\\\\"
    escape '\b' = "\\b"
    escape '\f' = "\\f"
    escape '\n' = "\\n"
    escape '\r' = "\\r"
    escape '\t' = "\\t"
    escape c
      | ord c < 0x20 = "\\u" ++ replicate (4 - length hex) '0' ++ hex
      | otherwise = [c]
      where
        hex = showHex (ord c) ""
