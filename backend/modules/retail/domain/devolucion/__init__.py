"""Devoluciones y cambios — vista 5 del handoff.

Es un agregado propio y no un método de `Venta` porque su ciclo de vida es
otro: la venta se cierra y se vuelve inmutable (INV-V1), y la devolución llega
días después, con su propio motivo, su propio método de reembolso y su propia
firma. Colgarla de la venta obligaría a reabrir un agregado cerrado, que es
justo lo que INV-V1 existe para impedir.
"""
