a = int(input("NUMBER 1: "))
b = int(input("NUMBER 2: "))
operation = input("Enter the operation (+, -, *, /): ")
if operation == "+":
    result = a + b
elif operation == "-":
    result = a - b
elif operation == "*":
    result = a * b
elif operation == "/":
    if b != 0:
        result = a / b
    else:
        print("Error: Division by zero is not allowed.")
        result = None
print("Result:", result)