"""Build or query a repository-scoped Python symbol graph snapshot."""

import argparse
import json

from structural_query import answer_structural_query
from symbol_graph import build_symbol_graph, load_symbol_graph, save_symbol_graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Build a graph JSON snapshot")
    build.add_argument("--repo-id", required=True)
    build.add_argument("--path", required=True)
    build.add_argument("--revision", required=True)
    build.add_argument("--output", required=True)
    query = commands.add_parser("query", help="Run a structural query against a snapshot")
    query.add_argument("--repo-id", required=True)
    query.add_argument("--revision", required=True)
    query.add_argument("--graph", required=True)
    query.add_argument("--question", required=True)
    args = parser.parse_args()
    if args.command == "build":
        graph = build_symbol_graph(args.path, args.repo_id, args.revision)
        save_symbol_graph(graph, args.output)
        result = {"repo_id": graph.repo_id, "revision": graph.revision,
                  "symbols": len(graph.symbols), "resolved_calls": len(graph.call_sites),
                  "unresolved_calls": len(graph.unresolved_calls),
                  "syntax_errors": graph.syntax_errors, "output": args.output}
    else:
        graph = load_symbol_graph(args.graph, args.repo_id, args.revision)
        result = answer_structural_query(graph, args.question)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
