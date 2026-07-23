def read_file(filename):
    """
    Read a file and return the file content.
    """

    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    return content

def gradient_colors(interval=8):
    colors = []

    for v in range(0, 256, interval):
        colors.append((v, v, v))

    for v in range(255 - interval, -1, -interval):
        colors.append((v, v, v))
    
    return colors