from parser.parser import parse_file

chunks = parse_file("test_code.py")

for chunk in chunks:
    print("\n------------------------------")
    print("Type:", chunk["type"])
    print("Name:", chunk["name"])
    print("File:", chunk["file"])
    print("Lines:", chunk["start_line"], "-", chunk["end_line"])
    print("Containing class:", chunk["containing_class"])
    print("Docstring:", chunk["docstring"])
    print("Imports:", chunk["imports"])
    print("Source:")
    print(chunk["source"])
