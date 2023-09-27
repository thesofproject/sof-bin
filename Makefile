clean:
	${RM} -r reproducible_images/ testruns/

# Delete caches too
distclean: clean
	${RM} -r tests/refs/ tests/refs_extracted/
