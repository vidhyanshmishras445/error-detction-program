string = input("enter a sentence:")
error_string = string.find("  ")
if error_string != -1:
    print("Error: Multiple spaces found at index", error_string)
else:    print("No multiple spaces found.")
if error_string != -1:
    correction = string.replace("  ", " ")
    print("Corrected string:", correction)
