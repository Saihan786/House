# don't consider budget or road costs
# might be easier to work with one blocktype for now

import matplotlib
import geopandas.geoseries
import matplotlib.pyplot as plt
import geopandas
import numpy as np

from shapely import Polygon, LineString, affinity, Point, intersection
from shapely import distance as dist


try:
    from .HRGenerator import ManageBlockTypes, generateBestTypes, generateBasicTypes, indexweightrandom
    from .RedLinePlot import getRLP, getPath
    from ..software import PolygonFunctions, LineFunctions
    matplotlib.use('agg')

except ImportError:
    from HRGenerator import ManageBlockTypes, generateBestTypes, generateBasicTypes, indexweightrandom
    from RedLinePlot import getRLP, getPath
    import PolygonFunctions, LineFunctions


X, Y = 0, 1
linep1idx, linep2idx = 0, 1


def fillMHT(mht):
    mht.addNewBlockType("ht1", 100000, 0, 25, 30)
    mht.addNewBlockType("ht2", 150000, 0, 50, 50)


def makeUnitPolygons(blocktypes):
    """Returns a list of unit polygons for each blocktype
    
    Unit polygons can be adjusted around the rlp by adding to its x and y values.

    """

    unitPolygons = []
    for bt in blocktypes:
        point1 = (0,0)
        point2 = (0+bt.WIDTH,0)
        point3 = (0,0+bt.LENGTH)
        point4 = (0+bt.WIDTH,0+bt.LENGTH)
        unitPolygons.append(Polygon([point1, point2, point4, point3, point1]))

    return unitPolygons


def findPadding(unitPolygons, longestline):
    """Returns blockpadding and rowpadding.
    
    Blockpadding is the largest parallel length of all unit polygons with a bit added.
    Rowpadding is the largest perpendicular length of all unit polygons with a bit added.

    Padding is calculated iteratively.
    
    """

    def calculateDistance(leq, padding=0, increment=10, showDistance=False):
        """Returns the (slightly increased) distance across the largest polygon, with respect to the
        given line equation.
        
        """
        
        originalx = 0
        originaly = LineFunctions.lineyval(leq, originalx)

        allups = []

        for up in unitPolygons:
            up1 = up2 = Polygon( [(c[X]+originalx,c[Y]+originaly) for c in list(up.exterior.coords)] )

            x=0
            while up1.intersects(up2):
                x += increment
                y = LineFunctions.lineyval(leq, x)
                up2 = Polygon( [(c[X]+x,c[Y]+y) for c in list(up.exterior.coords)] )
            
            distance = np.sqrt(np.square(x-originalx) + np.square(y-originaly))
            if padding<distance : padding = distance

            allups.append(up1)
            allups.append(up2)

        if showDistance:
            geopandas.GeoSeries([up.exterior for up in allups]).plot()
            plt.show()

        return padding

    leq = LineFunctions.lineEQ(longestline[linep1idx], longestline[linep2idx])
    blockpadding = calculateDistance(leq, showDistance=False)

    nleq = LineFunctions.normalLineEQ(leq, longestline[linep1idx])
    rowpadding = calculateDistance(nleq, showDistance=False)

    return (blockpadding, rowpadding)


def blocklines(path, distance, rlppolygon, pathIsHorizontal, ax=None, longestline=None):
    """Returns a list of all new lines, each from a point on the lines of the given path.

    The points are equidistant from each other at a given distance.
    
    The new lines have the given gradient m.
    
    """

    lines = []
    p1 = path[0][linep1idx]

    lleq = LineFunctions.lineEQ(longestline[linep1idx], longestline[linep2idx])
    nleq = LineFunctions.normalLineEQ(lleq, p1)

    if pathIsHorizontal:
        x = p1[X]

        points = []
        while x < path[ -1+len(path) ][linep2idx][X]:
            y = LineFunctions.lineyval(lleq, x)
            points.append( (x,y) )
            point = (x,y)
            
            nleq = LineFunctions.normalLineEQ(lleq, point)
            newline = LineFunctions.leqtoline(nleq, rlppolygon)
            lines.append(newline)
            
            x+=distance

    else:
        y = p1[Y]

        points = []
        while y > path[ -1+len(path) ][linep2idx][Y]:
            x = LineFunctions.linexval(nleq, y)
            points.append( (x,y) )
            point = (x,y)

            lleq = LineFunctions.normalLineEQ(nleq, point)
            newline = LineFunctions.leqtoline(lleq, rlppolygon)
            lines.append(newline)

            y-=distance

    return lines


def move_block_to_point(up, blockpoint, rlppolygon=None):
    """Returns a block that has been moved to the desired point.
    
    Optionally returns None if the block does not fit inside the polygon.

    Requires that the up has center origin to begin with.
    
    """
    
    corners = []
    for corner in up.exterior.coords[:-1]:
        corners.append( (corner[X]+blockpoint.coords[0][X] , corner[Y]+blockpoint.coords[0][Y]) )
    block = Polygon(corners)

    if (not rlppolygon) or rlppolygon.contains(block):
        return block
    else:
        return None
    

def filter_blocks(blocks_as_rows, smallest_up=None, replaceSmall=False):
    """Filters the blocks by removing the ones that overlap with another block.
    
    Returns filtered blocks as rows.

    Returns filtered blockpoints_as_rows (under same condition as filtered blocks).
    
    """
    
    distinctblocks = []

    for x in range(-1+len(blocks_as_rows)):
        row = []
        for y in range(len( blocks_as_rows[x] )):
            
            block = blocks_as_rows[x][y]
            keepBlock = True
            
            next = blocks_as_rows[x][y-1]
            if block.intersects(next):
                keepBlock=False

            for nextrowblock in blocks_as_rows[x+1]:
                if block.intersects(nextrowblock):
                    keepBlock=False

            if keepBlock:
                row.append(block)
            elif replaceSmall:
                row.append( move_block_to_point(smallest_up, block.centroid) )

        distinctblocks.append(row)
    distinctblocks.append( blocks_as_rows[ -1+len(blocks_as_rows) ] )

    return distinctblocks


def initPlot(rows_of_bps, unitPolygons, ax, rlppolygon, showInit=False):
    """Returns blockpoints (as rows) that will be included in next iteration.

    Creates an initial plot which only uses the smallest blocktype.
    
    """

    smallest_up = unitPolygons[0]
    for up in unitPolygons:
        if up.area < smallest_up.area:
            smallest_up = up


    blocks = []
    filtered_blockpoints_as_rows = []
    for row in rows_of_bps:
        newbprow = []
        newblockrow = []
        for blockpoint in row:
            block = move_block_to_point(smallest_up, blockpoint, rlppolygon)
            if block is not None:
                newblockrow.append(block)
                newbprow.append(blockpoint)
        blocks.append(newblockrow)
        filtered_blockpoints_as_rows.append(newbprow)

    distinctblocks = filter_blocks(blocks)

    if showInit:
        geopandas.GeoSeries([db.exterior for row in distinctblocks for db in row]).plot(ax=ax, color="green")
    return distinctblocks, filtered_blockpoints_as_rows


def replaceBlocks(rows_of_bps, unitPolygons, plot_blocktypes_as_rows, ax, rlppolygon):
    """Plots different blocktypes using weightedrandomness and an initial plot.
    
    If a block can't be replaced, it stays the same.
    
    """

    blocks_as_rows = []

    for x in range(len(rows_of_bps)):

        row = []
        for y in range(len( rows_of_bps[x] )):
            bp = rows_of_bps[x][y]
            bt = plot_blocktypes_as_rows[x][y]
            up = unitPolygons[bt]

            block = move_block_to_point(up, bp, rlppolygon)
            if block is not None:
                row.append(block)

        blocks_as_rows.append(row)

    smallest_up = unitPolygons[0]
    for up in unitPolygons:
        if up.area < smallest_up.area:
            smallest_up = up
    
    distinctblocks = filter_blocks(blocks_as_rows, smallest_up, replaceSmall=True)

    geopandas.GeoSeries([block.exterior for row in distinctblocks for block in row]).plot(ax=ax, color="green")
    return distinctblocks


def move_blocks_left(blocks, rlppolygon):
    """Moves all blocks left to minimise padding and open up space for more blocks."""
    
    for i in range(len(blocks)):
        prev = blocks[i-1]
        cur = blocks[i]

        # print(dist(prev, cur))
    

def plotProportions(blocktypes, unitPolygons, proportions, rlppolygon):
    """Plots all blocktypes on the rlp.
    
    The number of blocks of each bt depends on its proportion in proportions.
    
    Unit polygons are copied and moved around the rlp to create new blocks.

    Blockpadding is for perp lines, while Rowpadding is for parallel lines.
    
    """

    longestline = PolygonFunctions.findLongestLine(rlppolygon)

    unitPolygons = [PolygonFunctions.rotatePolygon(LineString(longestline), uP, showRotation=False) for uP in unitPolygons]
    unitPolygons = [PolygonFunctions.centerAtOrigin(uP, showTranslation=False) for uP in unitPolygons]

    horizontal_has_longest, (linePathX, mX), (linePathY, mY) = PolygonFunctions.findLinePaths(rlppolygon, showPaths=False)

    blockpadding, rowpadding = findPadding(unitPolygons, longestline)

    fig, ax = plt.subplots()

    if horizontal_has_longest:
        perpLines = blocklines(linePathX, blockpadding, rlppolygon, pathIsHorizontal=True, ax=ax, longestline=longestline)
        parallelLines = blocklines(linePathY, rowpadding, rlppolygon, pathIsHorizontal=False, ax=ax, longestline=longestline)            
    else:
        perpLines = blocklines(linePathX, rowpadding, rlppolygon, pathIsHorizontal=True, ax=ax, longestline=longestline)
        parallelLines = blocklines(linePathY, blockpadding, rlppolygon, pathIsHorizontal=False, ax=ax, longestline=longestline)            
    
    blockpoints = []
    rows_of_bps = []
    for l1 in parallelLines:
        row = []
        for l2 in perpLines:
            blockpoint = intersection(l1, l2)
            if not blockpoint.is_empty:
                blockpoints.append(blockpoint)
                row.append(blockpoint)
        rows_of_bps.append(row)
    
    smallBlocks_as_rows, blockpoints_as_rows = initPlot(rows_of_bps, unitPolygons, ax=ax, rlppolygon=rlppolygon, showInit=False)
    num_blocks = len( [bp for row in blockpoints_as_rows for bp in row] )

    plot_blocktypes_as_rows = indexweightrandom(numspaces=num_blocks, blocktypes=blocktypes, rows=blockpoints_as_rows)
    
    randomBlocks = replaceBlocks(blockpoints_as_rows, unitPolygons, plot_blocktypes_as_rows, ax, rlppolygon)
    # move_blocks_left(randomBlocks, rlppolygon)
    geopandas.GeoSeries(rlppolygon.exterior).plot(ax=ax, color="blue")

    plt.show()
    # return (fig, randomBlocks)



def example():
    rlp = getRLP(getPath())
    rlp = rlp.to_crs(epsg=27700)

    rlppolygon = rlp.geometry[0]
    
    mht = ManageBlockTypes()
    fillMHT(mht)
    blocktypes = mht.getBlockTypes()

    unitPolygons = makeUnitPolygons(blocktypes)

    bestproportions, profit = generateBestTypes(blocktypes, maxsize=rlppolygon.area, showResults=False)
    mht.addProportions(bestproportions)

    return plotProportions(blocktypes, unitPolygons, bestproportions, rlppolygon)


def startplot(rlp, showCloseToOrigin=True):
    rlp = rlp.to_crs(epsg=27700)
    rlppolygon = rlp.geometry[0]
    if showCloseToOrigin:
        rlppolygon = PolygonFunctions.moveToOrigin(rlppolygon)
    
    mht = ManageBlockTypes()
    fillMHT(mht)
    blocktypes = mht.getBlockTypes()

    unitPolygons = makeUnitPolygons(blocktypes)

    basicproportions = generateBasicTypes(mht.getBlockTypes(), maxsize=rlppolygon.area, showResults=False)
    mht.addProportions(basicproportions)
    return plotProportions(blocktypes, unitPolygons, basicproportions, rlppolygon)

example()