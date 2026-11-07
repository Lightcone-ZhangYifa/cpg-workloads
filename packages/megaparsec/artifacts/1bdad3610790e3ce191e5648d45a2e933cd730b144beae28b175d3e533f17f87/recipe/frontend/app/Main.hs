module Main (main) where

import CPG.Frontend
import qualified Control.Exception as E
import qualified Data.ByteString as BS
import Data.Either (isRight)
import qualified Data.Text as T
import qualified Data.Text.Encoding as TE
import System.Environment (getArgs)
import System.Exit (ExitCode (..), exitWith)

data Options = Options
  { optionRecover :: Bool,
    optionSourceName :: Maybe FilePath,
    optionFile :: Maybe FilePath
  }

data Action = Run Options | Help | Version

usage :: String
usage =
  unlines
    [ "cpg-megaparsec-frontend [--recover] [--source-name NAME] [FILE|-]",
      "cpg-megaparsec-frontend --version",
      "cpg-megaparsec-frontend --help",
      "",
      "Read UTF-8 from FILE, or stdin when FILE is omitted or '-'.",
      "Emit one JSON object. Exit 0: valid parse; 1: parse errors; 2: input/usage error.",
      "--recover collects errors by discarding through the next raw semicolon.",
      "Offsets count Unicode codepoints from zero; line/display-cell columns start at one.",
      "This fixture parses cpg-let-v1 syntax; it does not evaluate or compile programs."
    ]

parseOptions :: [String] -> Either String Action
parseOptions ["--help"] = Right Help
parseOptions ["--version"] = Right Version
parseOptions args = Run <$> go (Options False Nothing Nothing) args
  where
    go options [] = Right options
    go options ("--recover" : rest) = go options {optionRecover = True} rest
    go options ("--source-name" : value : rest) = go options {optionSourceName = Just value} rest
    go _ ["--source-name"] = Left "--source-name requires a value"
    go options ("--" : [filename]) = setFile options filename
    go _ ("--" : _) = Left "exactly one filename must follow --"
    go options (filename : rest)
      | filename /= "-" && take 1 filename == "-" = Left ("unknown option: " ++ filename)
      | otherwise = setFile options filename >>= \next -> go next rest
    setFile options filename = case optionFile options of
      Nothing -> Right options {optionFile = Just filename}
      Just _ -> Left "at most one input file may be supplied"

emit :: Json -> IO ()
emit value = BS.putStr (TE.encodeUtf8 (T.pack (renderJson value ++ "\n")))

failInput :: String -> String -> IO ()
failInput code message = emit (inputErrorJson code message) >> exitWith (ExitFailure 2)

main :: IO ()
main = do
  arguments <- getArgs
  case parseOptions arguments of
    Left problem -> failInput "invalid_arguments" (problem ++ "\n" ++ usage)
    Right Help -> putStr usage
    Right Version -> emit versionJson
    Right (Run options) -> run options

run :: Options -> IO ()
run options = do
  loaded <- E.try loadInput :: IO (Either E.IOException BS.ByteString)
  case loaded of
    Left problem -> failInput "io_error" (E.displayException problem)
    Right bytes -> case TE.decodeUtf8' bytes of
      Left problem -> failInput "invalid_utf8" (show problem)
      Right input -> do
        let result = parseProgram (optionRecover options) filename input
        emit (resultJson (optionRecover options) filename input result)
        exitWith (if isRight result then ExitSuccess else ExitFailure 1)
  where
    filename = case optionSourceName options of
      Just name -> name
      Nothing -> case optionFile options of
        Just path | path /= "-" -> path
        _ -> "<stdin>"
    loadInput = case optionFile options of
      Just path | path /= "-" -> BS.readFile path
      _ -> BS.getContents
